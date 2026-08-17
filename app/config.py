"""Typed local configuration loaded from the environment."""

import os
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, SecretStr

SQLITE_URL_PREFIX = "sqlite:///"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_DATABASE_PATH = "local_data/test-trigger.db"
DEFAULT_CHROMA_PERSIST_DIRECTORY = "local_data/chroma"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


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
        )


def _read(source: Mapping[str, str], key: str) -> Optional[str]:
    """Return a trimmed environment value, treating blank as unset."""
    value = source.get(key)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


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
