"""OpenAI-backed implementation of the structured-output provider."""

import json
from typing import Any, Dict, Optional

import openai

from app.config import AppSettings
from app.llm.errors import (
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.llm.provider import LLMProvider
from app.observability.logging import timed_step

DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenAIProvider(LLMProvider):
    """Calls the OpenAI chat completions API with a strict JSON schema.

    The API key is read from backend settings only. It is never logged, echoed
    into a response, or passed to the browser.
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        client: Optional[Any] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not settings.llm_enabled:
            raise ProviderNotConfiguredError(
                "OPENAI_API_KEY is not set; LLM features are disabled"
            )
        self._model = settings.openai_model
        self._timeout_seconds = timeout_seconds
        self._client = client or openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value()
        )

    def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> Dict[str, Any]:
        # Records the model, schema, and latency. The key is never a field.
        with timed_step(
            component="llm",
            step="extract_structured",
            model=self._model,
            schema_name=schema_name,
        ):
            return self._call(system_prompt, user_prompt, schema, schema_name)

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> Dict[str, Any]:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
                timeout=self._timeout_seconds,
            )
        except openai.APITimeoutError as error:
            raise ProviderTimeoutError(
                f"provider timed out after {self._timeout_seconds}s"
            ) from error
        except (openai.APIConnectionError, openai.APIStatusError) as error:
            raise ProviderUnavailableError(f"provider call failed: {error}") from error
        except openai.OpenAIError as error:
            raise ProviderUnavailableError(f"provider call failed: {error}") from error

        return _parse_content(response)


def _parse_content(response: Any) -> Dict[str, Any]:
    """Extract and parse the JSON body, treating any deviation as a failure."""
    try:
        choice = response.choices[0]
        content = choice.message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise ProviderResponseError("provider response had no message content") from error

    if choice.finish_reason == "length":
        raise ProviderResponseError("provider response was truncated")
    if not content:
        raise ProviderResponseError("provider returned empty content")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ProviderResponseError("provider returned malformed JSON") from error

    if not isinstance(parsed, dict):
        raise ProviderResponseError("provider returned a non-object payload")
    return parsed
