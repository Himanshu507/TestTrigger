"""Embedding provider interface and its OpenAI implementation."""

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Sequence

import openai

from app.config import AppSettings
from app.llm.errors import (
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

DEFAULT_TIMEOUT_SECONDS = 30.0


class EmbeddingProvider(ABC):
    """Turns text into vectors, or raises a typed provider error."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Return one vector per input text, in the same order."""


class NullEmbeddingProvider(EmbeddingProvider):
    """Stands in when no API key is configured, failing the same way an outage does."""

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise ProviderNotConfiguredError(
            "OPENAI_API_KEY is not set; embedding features are disabled"
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embeds text with the configured OpenAI embedding model."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        client: Optional[Any] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not settings.llm_enabled:
            raise ProviderNotConfiguredError(
                "OPENAI_API_KEY is not set; embedding features are disabled"
            )
        self._model = settings.openai_embedding_model
        self._timeout_seconds = timeout_seconds
        self._client = client or openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value()
        )

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        inputs = list(texts)
        if not inputs:
            return []

        try:
            response = self._client.embeddings.create(
                model=self._model, input=inputs, timeout=self._timeout_seconds
            )
        except openai.APITimeoutError as error:
            raise ProviderTimeoutError(
                f"embedding request timed out after {self._timeout_seconds}s"
            ) from error
        except openai.OpenAIError as error:
            raise ProviderUnavailableError(f"embedding request failed: {error}") from error

        try:
            vectors = [item.embedding for item in response.data]
        except (AttributeError, TypeError) as error:
            raise ProviderResponseError("embedding response was malformed") from error

        if len(vectors) != len(inputs):
            raise ProviderResponseError(
                f"expected {len(inputs)} embeddings, received {len(vectors)}"
            )
        return vectors
