"""Controlled test-catalog loading and filtering."""

import json
from pathlib import Path
from typing import Iterable

from app.models.test_case import TestCase


class TestCatalog:
    """Immutable, validated source of executable test definitions."""

    def __init__(self, test_cases: Iterable[TestCase]) -> None:
        self._test_cases = tuple(test_cases)
        self._by_id = {test_case.id: test_case for test_case in self._test_cases}
        if len(self._by_id) != len(self._test_cases):
            raise ValueError("test catalog contains duplicate IDs")

    @classmethod
    def load(cls, path: Path) -> "TestCatalog":
        with path.open(encoding="utf-8") as catalog_file:
            payload = json.load(catalog_file)

        if not isinstance(payload, list):
            raise ValueError("test catalog must contain a JSON array")
        return cls(TestCase.model_validate(test_case) for test_case in payload)

    @classmethod
    def load_default(cls) -> "TestCatalog":
        return cls.load(Path(__file__).resolve().parent.parent / "data" / "test_cases.json")

    def get(self, test_id: str) -> TestCase | None:
        return self._by_id.get(test_id)

    def all(self) -> list[TestCase]:
        return list(self._test_cases)

    def filter(
        self,
        *,
        module: str,
        scope: str,
        browser: str,
        region: str,
    ) -> list[TestCase]:
        return [
            test_case
            for test_case in self._test_cases
            if test_case.module == module
            and test_case.scope == scope
            and browser in test_case.browsers
            and region in test_case.regions
        ]
