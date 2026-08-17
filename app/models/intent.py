"""Structured interpretation of a natural-language request."""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.test_case import Browser, ModuleName, Region, TestScope

INTENT_FIELDS = ("module", "scope", "browser", "region", "environment")


class TestIntent(BaseModel):
    """Validated, normalized interpretation of a user query.

    Every field is optional because an incomplete request must be representable:
    the Intent Agent reports what it could not safely infer through
    ``missing_fields`` rather than guessing a value. Controlled enums mean the
    agent cannot introduce an unsupported module, browser, or region.
    """

    module: Optional[ModuleName] = None
    scope: Optional[TestScope] = None
    browser: Optional[Browser] = None
    region: Optional[Region] = None
    environment: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    missing_fields: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def missing_fields_must_be_unset_intent_fields(self) -> "TestIntent":
        for name in self.missing_fields:
            if name not in INTENT_FIELDS:
                raise ValueError(f"'{name}' is not an intent field")
            if getattr(self, name) is not None:
                raise ValueError(f"'{name}' is reported missing but has a value")
        if len(self.missing_fields) != len(set(self.missing_fields)):
            raise ValueError("missing_fields must not contain duplicates")
        return self

    @property
    def is_actionable(self) -> bool:
        """Report whether planning can proceed without clarification.

        Environment is not required: the planner and mock executor default it.
        """
        return not self.missing_fields and None not in (
            self.module,
            self.scope,
            self.browser,
            self.region,
        )
