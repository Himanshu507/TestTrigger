import pytest

from app.agents.normalization import (
    normalize_browser,
    normalize_module,
    normalize_region,
    normalize_scope,
)
from app.models.test_case import Browser, ModuleName, Region, TestScope


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("chrome", Browser.CHROME),
        ("Google Chrome", Browser.CHROME),
        ("  GOOGLE   chrome ", Browser.CHROME),
        ("Mozilla Firefox", Browser.FIREFOX),
        ("ff", Browser.FIREFOX),
        ("Safari", Browser.SAFARI),
    ],
)
def test_approved_browser_synonyms_resolve_to_catalog_values(raw, expected) -> None:
    assert normalize_browser(raw) is expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("US", Region.US),
        ("united states", Region.US),
        ("Nevada", Region.US_NEVADA),
        ("US-Nevada", Region.US_NEVADA),
        ("Europe", Region.EU),
        ("United Kingdom", Region.UK),
    ],
)
def test_approved_region_synonyms_resolve_to_catalog_values(raw, expected) -> None:
    assert normalize_region(raw) is expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("payment", ModuleName.PAYMENT),
        ("Payments", ModuleName.PAYMENT),
        ("sign in", ModuleName.LOGIN),
        ("withdrawals", ModuleName.WITHDRAWAL),
    ],
)
def test_approved_module_synonyms_resolve_to_catalog_values(raw, expected) -> None:
    assert normalize_module(raw) is expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("smoke", TestScope.SMOKE),
        ("Smoke Tests", TestScope.SMOKE),
        ("regression tests", TestScope.REGRESSION),
    ],
)
def test_approved_scope_synonyms_resolve_to_catalog_values(raw, expected) -> None:
    assert normalize_scope(raw) is expected


@pytest.mark.parametrize(
    "normalizer,unknown",
    [
        (normalize_browser, "edge"),
        (normalize_browser, "internet explorer"),
        (normalize_region, "canada"),
        (normalize_region, "us-california"),
        (normalize_module, "banking"),
        (normalize_scope, "performance"),
    ],
)
def test_unknown_values_are_rejected_rather_than_guessed(normalizer, unknown) -> None:
    assert normalizer(unknown) is None


@pytest.mark.parametrize(
    "normalizer",
    [normalize_browser, normalize_region, normalize_module, normalize_scope],
)
def test_absent_and_blank_values_resolve_to_none(normalizer) -> None:
    assert normalizer(None) is None
    assert normalizer("   ") is None
