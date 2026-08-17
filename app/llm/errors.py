"""Typed provider failures.

Callers map these to explicit workflow outcomes. An LLM failure is never
converted into a guessed answer.
"""


class ProviderError(RuntimeError):
    """Base class for every LLM provider failure."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when an LLM call is attempted without provider configuration."""


class ProviderTimeoutError(ProviderError):
    """Raised when the provider did not answer within the configured timeout."""


class ProviderUnavailableError(ProviderError):
    """Raised for transport failures and provider-side error responses."""


class ProviderResponseError(ProviderError):
    """Raised when a response arrives but is not usable structured output."""
