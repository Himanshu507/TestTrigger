"""Structured logging with secret redaction.

Every material step emits one JSON record carrying the workflow ID, component,
status, timing, and safe error context, so a run can be traced without reading
the database.

Redaction is applied at the logging boundary rather than trusted at every call
site: a credential must be impossible to log, not merely unlikely.
"""

import hashlib
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

LOGGER_NAME = "test_trigger"
REDACTED = "***redacted***"
DEFAULT_LEVEL = "INFO"

# Matched against lowercased key names, so `OPENAI_API_KEY` and `api_key` both
# redact. Substring matching catches suffixed variants such as `auth_token`.
SENSITIVE_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)

RESERVED_LOG_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def is_sensitive(key: str) -> bool:
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS)


def redact(value: Any) -> Any:
    """Return a copy with every sensitive value replaced, at any depth."""
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def fingerprint(value: Optional[str]) -> Optional[str]:
    """Hash an identifier that is safe to correlate but not to print.

    Used for idempotency keys: two records can be matched without publishing a
    client-chosen value.
    """
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in RESERVED_LOG_FIELDS or key.startswith("_"):
                continue
            payload[key] = REDACTED if is_sensitive(key) else redact(value)

        if record.exc_info:
            # The type and message are useful context; a traceback is not
            # something to emit into a shared log by default.
            exception = record.exc_info[1]
            payload["error_type"] = type(exception).__name__
            payload["error"] = str(exception)

        return json.dumps(payload, default=str)


def configure_logging(level: Optional[str] = None, stream=None) -> logging.Logger:
    """Install the JSON handler once. Safe to call repeatedly."""
    logger = logging.getLogger(LOGGER_NAME)
    resolved = (level or os.environ.get("LOG_LEVEL") or DEFAULT_LEVEL).upper()
    logger.setLevel(resolved)

    if not logger.handlers:
        handler = logging.StreamHandler(stream or sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_step(
    *,
    component: str,
    step: str,
    status: str,
    workflow_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    error_code: Optional[str] = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one structured record for a material step."""
    payload = {
        "component": component,
        "step": step,
        "status": status,
        "workflow_id": workflow_id,
        "duration_ms": duration_ms,
        "error_code": error_code,
        **fields,
    }
    get_logger().log(
        level,
        f"{component}.{step} {status}",
        extra={key: value for key, value in payload.items() if value is not None},
    )


@contextmanager
def timed_step(
    *, component: str, step: str, workflow_id: Optional[str] = None, **fields: Any
) -> Iterator[Dict[str, Any]]:
    """Time a step and log its outcome, including on failure.

    Yields a dict the caller can add fields to before the record is written.
    """
    started = time.perf_counter()
    extra: Dict[str, Any] = {}
    try:
        yield extra
    except Exception as error:
        log_step(
            component=component,
            step=step,
            status="failed",
            workflow_id=workflow_id,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            error_code=type(error).__name__,
            level=logging.ERROR,
            **{**fields, **extra},
        )
        raise
    log_step(
        component=component,
        step=step,
        status="completed",
        workflow_id=workflow_id,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        **{**fields, **extra},
    )
