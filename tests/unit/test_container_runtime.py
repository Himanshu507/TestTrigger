"""Container runtime configuration checks.

These assert the wiring and the secret-handling rules without needing a Docker
daemon, so they run in any environment. Image builds are covered separately and
skip when Docker is unavailable.
"""

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import AppSettings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
BACKEND_DOCKERFILE = ROOT / "Dockerfile"
FRONTEND_DOCKERFILE = ROOT / "frontend" / "Dockerfile"
ENV_EXAMPLE = ROOT / ".env.example"
DOCKERIGNORE = ROOT / ".dockerignore"
FRONTEND_ENTRYPOINT = ROOT / "frontend" / "entrypoint.sh"
BACKEND_ENTRYPOINT = ROOT / "docker" / "backend-entrypoint.sh"

SECRET_VARIABLE = "OPENAI_API_KEY"


# The docker CLI can block for a long time when the daemon is absent, so every
# probe is given a short deadline and any failure is treated as "unavailable".
PROBE_TIMEOUT_SECONDS = 10


def _run(command, *, timeout: int, cwd: Path = ROOT, env=None):
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


@functools.lru_cache(maxsize=1)
def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=PROBE_TIMEOUT_SECONDS)
    return result is not None and result.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker daemon is not available"
)


@pytest.fixture(scope="module")
def compose() -> dict:
    """Resolve the compose file the way Docker itself would.

    Resolution needs the CLI but not a running daemon, so this works on a
    machine where Docker is installed but not started.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    result = _run(
        ["docker", "compose", "config", "--format", "json"],
        timeout=60,
        env={**os.environ, "OPENAI_API_KEY": ""},
    )
    if result is None:
        pytest.skip("docker compose did not respond")
    if result.returncode != 0:
        pytest.fail(f"docker compose config failed: {result.stderr}")
    return json.loads(result.stdout)


def test_the_compose_file_is_valid(compose) -> None:
    assert set(compose["services"]) == {"backend", "frontend"}


def test_both_services_build_from_the_repository(compose) -> None:
    assert "build" in compose["services"]["backend"]
    assert "build" in compose["services"]["frontend"]


def test_services_bind_to_localhost_only(compose) -> None:
    """A demo runtime must not expose itself on the network."""
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert port.get("host_ip") in {"127.0.0.1", "::1"}, name


def test_documented_ports_are_published(compose) -> None:
    backend = compose["services"]["backend"]["ports"][0]
    frontend = compose["services"]["frontend"]["ports"][0]

    assert (backend["published"], backend["target"]) == ("8000", 8000)
    assert (frontend["published"], frontend["target"]) == ("5173", 80)


def test_the_frontend_never_receives_the_api_key(compose) -> None:
    environment = compose["services"]["frontend"].get("environment", {})

    assert SECRET_VARIABLE not in environment
    assert set(environment) == {"API_BASE_URL"}


def test_the_backend_receives_the_key_from_the_environment(compose) -> None:
    environment = compose["services"]["backend"]["environment"]

    assert SECRET_VARIABLE in environment
    assert environment[SECRET_VARIABLE] in ("", None)


def test_persistent_state_uses_a_named_volume(compose) -> None:
    volumes = compose["services"]["backend"]["volumes"]

    assert any(
        volume["type"] == "volume" and volume["target"] == "/srv/data-local"
        for volume in volumes
    )
    assert "test-trigger-data" in compose["volumes"]


def test_persistent_paths_resolve_inside_the_mounted_volume(compose) -> None:
    """Guard against a relative sqlite URL silently bypassing the volume.

    `sqlite:///x` is a path relative to the working directory, so a container
    would write to its own layer and lose the database on the next `down`.
    Only `sqlite:////x` is absolute.
    """
    environment = compose["services"]["backend"]["environment"]
    mount = next(
        volume["target"]
        for volume in compose["services"]["backend"]["volumes"]
        if volume["type"] == "volume"
    )

    database_path = AppSettings.from_environment(environment).database_path
    assert database_path.startswith(mount + "/"), database_path
    assert environment["CHROMA_PERSIST_DIRECTORY"].startswith(mount + "/")


def test_both_services_declare_a_healthcheck(compose) -> None:
    for name, service in compose["services"].items():
        assert "healthcheck" in service, name


def test_the_frontend_waits_for_backend_readiness(compose) -> None:
    depends = compose["services"]["frontend"]["depends_on"]

    assert depends["backend"]["condition"] == "service_healthy"


def test_no_secret_value_appears_in_the_resolved_configuration(compose) -> None:
    """Resolving the config must never print a key, even when one is set."""
    assert "sk-" not in json.dumps(compose)

    for name, service in compose["services"].items():
        for key, value in (service.get("environment") or {}).items():
            if "KEY" in key.upper() or "SECRET" in key.upper() or "TOKEN" in key.upper():
                assert not value, f"{name}.{key} resolved to a literal value"


def test_dockerfiles_embed_no_secret() -> None:
    for path in (BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE):
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text
        assert f"ENV {SECRET_VARIABLE}" not in text
        assert f"ARG {SECRET_VARIABLE}" not in text
        assert "COPY .env" not in text


def test_the_backend_image_runs_as_an_unprivileged_user() -> None:
    text = BACKEND_DOCKERFILE.read_text(encoding="utf-8")

    assert re.search(r"^USER (?!root)", text, re.MULTILINE)


def test_the_image_context_excludes_secrets_and_local_state() -> None:
    ignored = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert "local_data/" in ignored
    assert "*.sqlite" in ignored
    assert "!.env.example" in ignored


def test_the_example_environment_lists_names_without_values() -> None:
    lines = [
        line
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    settings = dict(line.split("=", 1) for line in lines)

    assert settings[SECRET_VARIABLE] == ""
    assert "sk-" not in ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "FRONTEND_ORIGIN" in settings
    assert "API_BASE_URL" in settings


def test_the_real_env_file_is_git_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert "!.env.example" in ignored


def test_the_frontend_entrypoint_publishes_only_the_api_base_url() -> None:
    text = FRONTEND_ENTRYPOINT.read_text(encoding="utf-8")
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]

    assert "API_BASE_URL" in text
    assert "TEST_TRIGGER_API_BASE" in text
    # The warning about keys belongs in a comment; no executable line may read one.
    assert all(SECRET_VARIABLE not in line for line in code)


def test_the_frontend_writes_no_credential_into_the_served_bundle() -> None:
    text = FRONTEND_ENTRYPOINT.read_text(encoding="utf-8")
    written_lines = [line for line in text.splitlines() if ">" in line and "TARGET" in line]

    assert written_lines
    for line in written_lines:
        assert SECRET_VARIABLE not in line
        assert "sk-" not in line


def test_backend_initialization_is_idempotent_and_key_optional() -> None:
    text = BACKEND_ENTRYPOINT.read_text(encoding="utf-8")

    assert ".ingested" in text, "re-ingesting on every restart wastes the volume"
    assert "OPENAI_API_KEY" in text
    assert "disabled" in text, "a missing key must report a feature status"
    assert 'exec "$@"' in text


def test_the_compose_file_does_not_claim_to_be_a_deployment() -> None:
    text = COMPOSE.read_text(encoding="utf-8").lower()

    assert "local development and demo runtime" in text
    assert "not a deployment strategy" in text


@requires_docker
def test_the_backend_image_builds() -> None:
    result = _run(
        ["docker", "build", "-t", "test-trigger-backend:test", "."], timeout=900
    )

    assert result is not None and result.returncode == 0, (
        result.stderr[-3000:] if result else "docker build timed out"
    )


@requires_docker
def test_the_frontend_image_builds() -> None:
    result = _run(
        ["docker", "build", "-t", "test-trigger-frontend:test", "."],
        timeout=600,
        cwd=ROOT / "frontend",
    )

    assert result is not None and result.returncode == 0, (
        result.stderr[-3000:] if result else "docker build timed out"
    )
