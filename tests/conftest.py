"""Shared test configuration."""

import logging

import pytest

from app.observability.logging import LOGGER_NAME


@pytest.fixture(autouse=True, scope="session")
def quiet_application_logging():
    """Keep structured logs out of the test run.

    The application logs one JSON record per material step. Formatting and
    writing those for every test is pure overhead — it made the suite roughly
    forty times slower — and the records themselves are verified directly in
    tests/unit/test_logging.py, which installs its own capturing handler.
    """
    logger = logging.getLogger(LOGGER_NAME)
    previous_level = logger.level
    previous_handlers = list(logger.handlers)

    logger.handlers = [logging.NullHandler()]
    logger.setLevel(logging.WARNING)

    yield

    logger.handlers = previous_handlers
    logger.setLevel(previous_level)
