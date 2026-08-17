"""Test-catalog domain models."""

from enum import Enum
from typing import List

from pydantic import BaseModel, Field, field_validator


class ModuleName(str, Enum):
    PAYMENT = "payment"
    WALLET = "wallet"
    CHECKOUT = "checkout"
    LOGIN = "login"
    WITHDRAWAL = "withdrawal"


class TestScope(str, Enum):
    SMOKE = "smoke"
    REGRESSION = "regression"


class Browser(str, Enum):
    CHROME = "chrome"
    FIREFOX = "firefox"
    SAFARI = "safari"


class Region(str, Enum):
    US = "US"
    US_NEVADA = "US-Nevada"
    EU = "EU"
    UK = "UK"


class Criticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TestCase(BaseModel):
    """An executable test definition from the controlled catalog."""

    id: str = Field(pattern=r"^[A-Z]{3}-\d{3}$")
    name: str = Field(min_length=1)
    module: ModuleName
    scope: TestScope
    browsers: List[Browser] = Field(min_length=1)
    regions: List[Region] = Field(min_length=1)
    criticality: Criticality
    description: str = Field(min_length=1)

    @field_validator("browsers", "regions")
    @classmethod
    def values_must_be_unique(cls, values: list[Enum]) -> list[Enum]:
        if len(values) != len(set(values)):
            raise ValueError("controlled values must not contain duplicates")
        return values
