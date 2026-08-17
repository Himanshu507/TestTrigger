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


def test_non_sqlite_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="sqlite"):
        AppSettings.from_environment(
            {"DATABASE_URL": "postgresql://localhost/test_trigger"}
        )
