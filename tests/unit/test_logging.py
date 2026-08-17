import io
import json
import logging

import pytest

from app.observability.logging import (
    REDACTED,
    JsonFormatter,
    configure_logging,
    fingerprint,
    get_logger,
    is_sensitive,
    log_step,
    redact,
    timed_step,
)


@pytest.fixture
def captured():
    """Attach a capturing JSON handler for the duration of one test."""
    stream = io.StringIO()
    logger = get_logger()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    previous = list(logger.handlers)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield stream
    logger.handlers = previous


def _records(stream) -> list:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_a_step_logs_the_documented_fields(captured) -> None:
    log_step(
        component="workflow",
        step="planning",
        status="completed",
        workflow_id="WF-1001",
        duration_ms=12.5,
    )

    record = _records(captured)[0]
    assert record["component"] == "workflow"
    assert record["step"] == "planning"
    assert record["status"] == "completed"
    assert record["workflow_id"] == "WF-1001"
    assert record["duration_ms"] == 12.5
    assert record["timestamp"]
    assert record["level"] == "INFO"


def test_every_record_is_a_single_json_object(captured) -> None:
    log_step(component="llm", step="extract", status="completed")
    log_step(component="llm", step="extract", status="failed", error_code="Timeout")

    lines = captured.getvalue().splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "OPENAI_API_KEY",
        "openai_api_key",
        "authorization",
        "auth_token",
        "client_secret",
        "password",
    ],
)
def test_sensitive_field_names_are_recognized(key) -> None:
    assert is_sensitive(key)


def test_a_sensitive_field_is_never_written(captured) -> None:
    log_step(
        component="llm",
        step="extract",
        status="completed",
        api_key="sk-live-abcdef123456",
        model="gpt-test",
    )

    record = _records(captured)[0]
    assert record["api_key"] == REDACTED
    assert "sk-live-abcdef123456" not in captured.getvalue()
    assert record["model"] == "gpt-test"


def test_redaction_reaches_nested_values() -> None:
    payload = {
        "settings": {"openai_api_key": "sk-live-1", "model": "gpt-test"},
        "items": [{"token": "secret-value"}, {"name": "safe"}],
    }

    cleaned = redact(payload)

    assert cleaned["settings"]["openai_api_key"] == REDACTED
    assert cleaned["settings"]["model"] == "gpt-test"
    assert cleaned["items"][0]["token"] == REDACTED
    assert cleaned["items"][1]["name"] == "safe"


def test_nested_secrets_in_a_logged_field_are_redacted(captured) -> None:
    log_step(
        component="config",
        step="load",
        status="completed",
        settings={"openai_api_key": "sk-live-2", "database_path": "local.db"},
    )

    assert "sk-live-2" not in captured.getvalue()
    assert "local.db" in captured.getvalue()


def test_a_fingerprint_correlates_without_disclosing() -> None:
    value = "client-supplied-idempotency-key"

    digest = fingerprint(value)

    assert digest == fingerprint(value)
    assert digest != fingerprint("other")
    assert value not in digest
    assert fingerprint(None) is None


def test_a_timed_step_records_duration_on_success(captured) -> None:
    with timed_step(component="workflow", step="retrieval", workflow_id="WF-1001"):
        pass

    record = _records(captured)[0]
    assert record["status"] == "completed"
    assert record["duration_ms"] >= 0


def test_a_timed_step_logs_and_reraises_on_failure(captured) -> None:
    with pytest.raises(ValueError):
        with timed_step(component="workflow", step="retrieval", workflow_id="WF-1001"):
            raise ValueError("boom")

    record = _records(captured)[0]
    assert record["status"] == "failed"
    assert record["error_code"] == "ValueError"
    assert record["level"] == "ERROR"
    assert record["duration_ms"] >= 0


def test_a_timed_step_carries_fields_added_by_the_caller(captured) -> None:
    with timed_step(component="workflow", step="intent") as extra:
        extra["resulting_status"] = "intent_parsed"

    assert _records(captured)[0]["resulting_status"] == "intent_parsed"


def test_an_exception_logs_its_type_and_message_without_a_traceback(captured) -> None:
    try:
        raise RuntimeError("provider exploded")
    except RuntimeError:
        get_logger().error("failed", exc_info=True)

    record = _records(captured)[0]
    assert record["error_type"] == "RuntimeError"
    assert record["error"] == "provider exploded"
    assert "Traceback" not in captured.getvalue()


def test_configuring_twice_does_not_duplicate_handlers() -> None:
    logger = get_logger()
    previous = list(logger.handlers)
    logger.handlers = []
    try:
        configure_logging(level="INFO")
        configure_logging(level="INFO")
        assert len(logger.handlers) == 1
    finally:
        logger.handlers = previous
