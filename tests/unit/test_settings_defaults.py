import pytest

from app.config import AppSettings


def test_missing_llm_configuration_disables_ai_calls_instead_of_failing() -> None:
    settings = AppSettings.from_environment({})

    assert settings.openai_api_key is None
    assert settings.llm_enabled is False
    assert settings.openai_model
    assert settings.database_path


def test_present_api_key_enables_llm_paths() -> None:
    settings = AppSettings.from_environment({"OPENAI_API_KEY": "test-key"})

    assert settings.llm_enabled is True


def test_blank_environment_values_are_treated_as_unset() -> None:
    settings = AppSettings.from_environment({"OPENAI_API_KEY": "   ", "OPENAI_MODEL": ""})

    assert settings.llm_enabled is False
    assert settings.openai_model == AppSettings().openai_model


def test_secret_is_masked_in_representations() -> None:
    settings = AppSettings.from_environment({"OPENAI_API_KEY": "super-secret-value"})

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings.model_dump())


def test_absolute_sqlite_url_keeps_its_leading_slash() -> None:
    settings = AppSettings.from_environment(
        {"DATABASE_URL": "sqlite:////var/data/test-trigger.db"}
    )

    assert settings.database_path == "/var/data/test-trigger.db"


def test_confidence_threshold_and_timeout_are_configurable() -> None:
    settings = AppSettings.from_environment(
        {"INTENT_CONFIDENCE_THRESHOLD": "0.85", "LLM_TIMEOUT_SECONDS": "12"}
    )

    assert settings.intent_confidence_threshold == 0.85
    assert settings.llm_timeout_seconds == 12.0


def test_unparseable_numeric_setting_fails_loudly() -> None:
    with pytest.raises(ValueError, match="INTENT_CONFIDENCE_THRESHOLD"):
        AppSettings.from_environment({"INTENT_CONFIDENCE_THRESHOLD": "high"})


def test_confidence_threshold_must_be_a_probability() -> None:
    with pytest.raises(ValueError):
        AppSettings.from_environment({"INTENT_CONFIDENCE_THRESHOLD": "1.5"})


def test_both_loopback_hostnames_are_allowed_origins() -> None:
    """A browser treats localhost and 127.0.0.1 as different origins."""
    settings = AppSettings.from_environment(
        {"FRONTEND_ORIGIN": "http://localhost:5173"}
    )

    assert settings.frontend_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_the_sibling_is_added_for_either_spelling() -> None:
    settings = AppSettings.from_environment(
        {"FRONTEND_ORIGIN": "http://127.0.0.1:3000"}
    )

    assert "http://localhost:3000" in settings.frontend_origins


def test_several_origins_may_be_configured() -> None:
    settings = AppSettings.from_environment(
        {"FRONTEND_ORIGIN": "http://localhost:5173, http://localhost:4173"}
    )

    assert settings.frontend_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


def test_a_non_loopback_origin_gains_no_sibling() -> None:
    settings = AppSettings.from_environment(
        {"FRONTEND_ORIGIN": "https://testing.internal"}
    )

    assert settings.frontend_origins == ["https://testing.internal"]


def test_non_sqlite_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="sqlite"):
        AppSettings.from_environment(
            {"DATABASE_URL": "postgresql://localhost/test_trigger"}
        )
