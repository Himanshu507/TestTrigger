"""SQLite schema for durable workflow and audit records.

Table responsibilities are defined in docs/data-model.md. Every dependent table
references ``workflows(id)`` so a run can be reconstructed and audited.
"""

from typing import Tuple

SCHEMA_STATEMENTS: Tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        query TEXT NOT NULL,
        status TEXT NOT NULL,
        dry_run INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        agent_name TEXT NOT NULL,
        status TEXT NOT NULL,
        input_payload TEXT NOT NULL,
        output_payload TEXT,
        error TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        test_id TEXT NOT NULL,
        priority INTEGER NOT NULL,
        risk_score REAL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        external_job_id TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id INTEGER NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
        test_id TEXT NOT NULL,
        status TEXT NOT NULL,
        duration_ms INTEGER,
        failure_reason TEXT,
        recorded_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        summary TEXT NOT NULL,
        analysis_payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        step TEXT NOT NULL,
        status TEXT NOT NULL,
        metadata TEXT,
        occurred_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_workflow ON agent_runs(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_test_plans_workflow ON test_plans(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_executions_workflow ON executions(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_test_results_execution ON test_results(execution_id)",
    "CREATE INDEX IF NOT EXISTS idx_workflow_events_workflow ON workflow_events(workflow_id)",
)
