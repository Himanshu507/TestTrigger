"""Provider-agnostic structured-output interface.

Agents depend on this abstraction rather than a vendor SDK, which keeps the
seam for a future provider and makes fakes trivial in tests.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class LLMProvider(ABC):
    """Returns schema-constrained JSON, or raises a typed provider error."""

    @abstractmethod
    def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Dict[str, Any],
        schema_name: str,
    ) -> Dict[str, Any]:
        """Return parsed structured output for the given prompt and schema.

        Raises:
            ProviderTimeoutError: the provider exceeded the configured timeout.
            ProviderUnavailableError: transport failure or provider-side error.
            ProviderResponseError: a response arrived but was not usable JSON.
        """
