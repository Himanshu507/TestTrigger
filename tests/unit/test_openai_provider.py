import json
from types import SimpleNamespace

import openai
import pytest

from app.config import AppSettings
from app.llm.errors import (
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.llm.openai_provider import OpenAIProvider

SCHEMA = {"type": "object", "properties": {"module": {"type": "string"}}}
SETTINGS = AppSettings.from_environment(
    {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-test"}
)


class FakeCompletions:
    def __init__(self, response=None, error: Exception = None) -> None:
        self.response = response
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error: Exception = None) -> None:
        self.completions = FakeCompletions(response, error)
        self.chat = SimpleNamespace(completions=self.completions)


def _response(content, finish_reason: str = "stop"):
    message = SimpleNamespace(content=content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _provider(client: FakeClient) -> OpenAIProvider:
    return OpenAIProvider(SETTINGS, client=client, timeout_seconds=5.0)


def test_provider_requires_configuration() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        OpenAIProvider(AppSettings.from_environment({}))


def test_structured_output_is_parsed_and_returned() -> None:
    client = FakeClient(_response(json.dumps({"module": "payment"})))

    result = _provider(client).extract_structured(
        system_prompt="system",
        user_prompt="user",
        schema=SCHEMA,
        schema_name="test_intent",
    )

    assert result == {"module": "payment"}


def test_request_pins_the_model_schema_and_timeout() -> None:
    client = FakeClient(_response(json.dumps({"module": "payment"})))

    _provider(client).extract_structured(
        system_prompt="system",
        user_prompt="user",
        schema=SCHEMA,
        schema_name="test_intent",
    )

    kwargs = client.completions.kwargs
    assert kwargs["model"] == "gpt-test"
    assert kwargs["timeout"] == 5.0
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["response_format"]["json_schema"]["schema"] == SCHEMA


def test_timeout_maps_to_a_typed_timeout_error() -> None:
    client = FakeClient(error=openai.APITimeoutError(request=None))

    with pytest.raises(ProviderTimeoutError):
        _provider(client).extract_structured(
            system_prompt="s", user_prompt="u", schema=SCHEMA, schema_name="n"
        )


def test_connection_failure_maps_to_a_typed_unavailable_error() -> None:
    client = FakeClient(error=openai.APIConnectionError(request=None))

    with pytest.raises(ProviderUnavailableError):
        _provider(client).extract_structured(
            system_prompt="s", user_prompt="u", schema=SCHEMA, schema_name="n"
        )


@pytest.mark.parametrize(
    "response",
    [
        _response("not json at all"),
        _response(""),
        _response(json.dumps(["a", "list"])),
        _response(json.dumps({"module": "payment"}), finish_reason="length"),
        SimpleNamespace(choices=[]),
    ],
)
def test_unusable_responses_map_to_a_typed_response_error(response) -> None:
    with pytest.raises(ProviderResponseError):
        _provider(FakeClient(response)).extract_structured(
            system_prompt="s", user_prompt="u", schema=SCHEMA, schema_name="n"
        )


def test_api_key_is_not_exposed_by_the_provider() -> None:
    provider = _provider(FakeClient(_response(json.dumps({}))))

    assert "test-key" not in repr(provider)
    assert "test-key" not in repr(SETTINGS)
