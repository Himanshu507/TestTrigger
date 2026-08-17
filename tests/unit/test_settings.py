from app.config import AppSettings


def test_settings_loads_openai_configuration_from_environment() -> None:
    settings = AppSettings.from_environment(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-test",
            "OPENAI_EMBEDDING_MODEL": "text-embedding-test",
            "DATABASE_URL": "sqlite:///tmp/test-trigger.db",
            "CHROMA_PERSIST_DIRECTORY": "tmp/chroma",
            "FRONTEND_ORIGIN": "http://localhost:3000",
        }
    )

    assert settings.openai_api_key.get_secret_value() == "test-key"
    assert settings.openai_model == "gpt-test"
    assert settings.database_path == "tmp/test-trigger.db"
    assert settings.frontend_origin == "http://localhost:3000"
