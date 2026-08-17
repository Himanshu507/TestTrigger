import sqlite3

import pytest

from app.db.database import Database

DOCUMENTED_TABLES = {
    "workflows",
    "agent_runs",
    "test_plans",
    "executions",
    "test_results",
    "analysis_reports",
    "workflow_events",
}


def test_initialize_creates_every_documented_table(tmp_path) -> None:
    database = Database(tmp_path / "test-trigger.db")

    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    assert DOCUMENTED_TABLES <= {row["name"] for row in rows}


def test_initialize_is_safe_to_run_twice(tmp_path) -> None:
    database = Database(tmp_path / "test-trigger.db")

    database.initialize()
    database.initialize()

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 0


def test_agent_run_cannot_reference_a_missing_workflow(tmp_path) -> None:
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()

    with pytest.raises(sqlite3.IntegrityError):
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (
                    workflow_id, agent_name, status, input_payload, started_at
                )
                VALUES ('WF-9999', 'intent', 'completed', '{}', '2026-08-17T10:00:00+00:00')
                """
            )


def test_failed_write_is_rolled_back(tmp_path) -> None:
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()

    with pytest.raises(RuntimeError):
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (id, query, status, dry_run, created_at, updated_at)
                VALUES ('WF-1001', 'q', 'received', 0, 'now', 'now')
                """
            )
            raise RuntimeError("caller failed after writing")

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 0
