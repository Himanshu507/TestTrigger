"""SQLite connection management and schema bootstrap."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

from app.db.schema import SCHEMA_STATEMENTS


class Database:
    """Owns the local SQLite file, connections, and schema creation."""

    def __init__(self, path: Union[Path, str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection with foreign keys enforced and row access by name.

        Commits on success, rolls back on failure, and always closes.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create every documented table on a clean or existing database."""
        with self.connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
