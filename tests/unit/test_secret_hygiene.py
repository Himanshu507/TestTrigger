"""Repository-wide secret hygiene checks (QLT-6).

A committed credential is not a bug you notice at review time, so this runs
with the rest of the suite. It scans what git actually tracks rather than the
working tree, since that is what would be published.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Patterns for provider keys that must never reach the repository. The example
# strings in this file are deliberately shaped so they cannot match themselves.
CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

# Assignments of a real-looking value to a secret-shaped name.
ASSIGNMENT = re.compile(
    r"""(?ix)
    (api[_-]?key|secret|password|token)
    \s*[:=]\s*
    ["']([^"'\s$*{}<>]{12,})["']
    """
)

SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}
SKIP_NAMES = {"uv.lock", "test_secret_hygiene.py"}


def _tracked_files() -> list:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        pytest.skip("not a git repository")
    return [line for line in result.stdout.splitlines() if line]


def _readable_tracked_files():
    for relative in _tracked_files():
        path = ROOT / relative
        if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
            continue
        if not path.is_file():
            continue
        try:
            yield relative, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_credential_pattern_is_committed() -> None:
    offenders = []
    for relative, text in _readable_tracked_files():
        for pattern in CREDENTIAL_PATTERNS:
            match = pattern.search(text)
            if match:
                offenders.append(f"{relative}: {pattern.pattern}")

    assert not offenders, "possible credentials committed: " + ", ".join(offenders)


def test_no_secret_shaped_assignment_carries_a_literal_value() -> None:
    offenders = []
    for relative, text in _readable_tracked_files():
        for match in ASSIGNMENT.finditer(text):
            value = match.group(2)
            # Placeholders and env references are expected. A test fixture that
            # must occupy a secret-shaped field declares itself with a `fake-`
            # prefix, so an exemption is visible at the value rather than hidden
            # in a file-level allowlist here.
            if value.startswith(("$", "${", "<", "your-", "example", "fake-")):
                continue
            if value in {"test-key", "client-key-1", "e2e-key", "key-1"}:
                continue
            if "REDACTED" in value or value.strip("*") == "":
                continue
            offenders.append(f"{relative}: {match.group(1)}={value[:12]}...")

    assert not offenders, "literal secret assignments: " + ", ".join(offenders)


def test_the_env_file_is_not_tracked() -> None:
    tracked = set(_tracked_files())

    assert ".env" not in tracked
    assert not any(
        name.startswith(".env") and name != ".env.example" for name in tracked
    )


def test_the_example_env_file_is_tracked_and_empty_of_values() -> None:
    assert ".env.example" in _tracked_files()

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^OPENAI_API_KEY=\s*$", text, re.MULTILINE)


def test_no_local_database_or_vector_store_is_tracked() -> None:
    tracked = _tracked_files()

    assert not [name for name in tracked if name.endswith((".db", ".sqlite", ".sqlite3"))]
    assert not [name for name in tracked if name.startswith(("local_data/", "chroma_"))]


def test_the_frontend_bundle_contains_no_provider_credential() -> None:
    for name in ("app.js", "index.html", "styles.css"):
        text = (ROOT / "frontend" / name).read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" not in text
        assert not any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS)
