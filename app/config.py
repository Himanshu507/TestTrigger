"""Typed local configuration loaded from the environment."""

import os
from typing import List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr

SQLITE_URL_PREFIX = "sqlite:///"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_DATABASE_PATH = "local_data/test-trigger.db"
DEFAULT_CHROMA_PERSIST_DIRECTORY = "local_data/chroma"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_INTENT_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0


class AppSettings(BaseModel):
    """Backend-only settings.

    The OpenAI key is held as a ``SecretStr`` so it is masked in reprs and logs.
    It is never exposed to the browser, persisted, or placed in a response body.
    """

    model_config = ConfigDict(frozen=True)

    openai_api_key: Optional[SecretStr] = None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_embedding_model: str = DEFAULT_OPENAI_EMBEDDING_MODEL
    database_path: str = DEFAULT_DATABASE_PATH
    chroma_persist_directory: str = DEFAULT_CHROMA_PERSIST_DIRECTORY
    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN
    intent_confidence_threshold: float = Field(
        default=DEFAULT_INTENT_CONFIDENCE_THRESHOLD, ge=0.0, le=1.0
    )
    llm_timeout_seconds: float = Field(default=DEFAULT_LLM_TIMEOUT_SECONDS, gt=0.0)

    @property
    def frontend_origins(self) -> List[str]:
        """Browser origins allowed by CORS.

        `FRONTEND_ORIGIN` may list several, comma separated. Each entry also
        contributes its loopback sibling, because `localhost:5173` and
        `127.0.0.1:5173` are different origins to a browser and a local user
        will reasonably type either one.
        """
        origins: List[str] = []
        for entry in self.frontend_origin.split(","):
            origin = entry.strip()
            if not origin:
                continue
            for candidate in (origin, _loopback_sibling(origin)):
                if candidate and candidate not in origins:
                    origins.append(candidate)
        return origins

    @property
    def llm_enabled(self) -> bool:
        """Report whether LLM and embedding calls are configured.

        A missing key disables AI paths rather than failing startup: the
        deterministic core must remain usable without a provider.
        """
        return self.openai_api_key is not None

    @classmethod
    def from_environment(
        cls, environment: Optional[Mapping[str, str]] = None
    ) -> "AppSettings":
        source = os.environ if environment is None else environment

        api_key = _read(source, "OPENAI_API_KEY")
        database_url = _read(source, "DATABASE_URL")

        return cls(
            openai_api_key=SecretStr(api_key) if api_key is not None else None,
            openai_model=_read(source, "OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
            openai_embedding_model=(
                _read(source, "OPENAI_EMBEDDING_MODEL")
                or DEFAULT_OPENAI_EMBEDDING_MODEL
            ),
            database_path=(
                _database_path(database_url)
                if database_url is not None
                else DEFAULT_DATABASE_PATH
            ),
            chroma_persist_directory=(
                _read(source, "CHROMA_PERSIST_DIRECTORY")
                or DEFAULT_CHROMA_PERSIST_DIRECTORY
            ),
            frontend_origin=(
                _read(source, "FRONTEND_ORIGIN") or DEFAULT_FRONTEND_ORIGIN
            ),
            intent_confidence_threshold=_read_float(
                source, "INTENT_CONFIDENCE_THRESHOLD", DEFAULT_INTENT_CONFIDENCE_THRESHOLD
            ),
            llm_timeout_seconds=_read_float(
                source, "LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS
            ),
        )


LOOPBACK_HOSTS = (("localhost", "127.0.0.1"), ("127.0.0.1", "localhost"))


def _loopback_sibling(origin: str) -> Optional[str]:
    """Return the same origin addressed by the other loopback hostname."""
    for host, sibling in LOOPBACK_HOSTS:
        if f"//{host}:" in origin or origin.endswith(f"//{host}"):
            return origin.replace(host, sibling, 1)
    return None


def _read(source: Mapping[str, str], key: str) -> Optional[str]:
    """Return a trimmed environment value, treating blank as unset."""
    value = source.get(key)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _read_float(source: Mapping[str, str], key: str, default: float) -> float:
    """Read a numeric setting, failing loudly rather than silently defaulting."""
    value = _read(source, key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{key} must be a number, got {value!r}") from error


def _database_path(database_url: str) -> str:
    """Convert a SQLite URL into the local file path used by ``Database``."""
    if not database_url.startswith(SQLITE_URL_PREFIX):
        raise ValueError(
            f"DATABASE_URL must start with '{SQLITE_URL_PREFIX}'; "
            "the MVP supports SQLite only"
        )
    path = database_url[len(SQLITE_URL_PREFIX) :]
    if not path:
        raise ValueError("DATABASE_URL does not contain a database path")
    return path
