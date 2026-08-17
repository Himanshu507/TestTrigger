"""Approved synonym resolution for controlled vocabulary.

This is the second validation gate. Provider schema parsing constrains output
once; this maps known surface variations onto catalog values and returns None
for anything unrecognized. An unknown value is reported as missing, never
coerced into the nearest supported value.
"""

from enum import Enum
from typing import Dict, Optional, Type, TypeVar

from app.models.test_case import Browser, ModuleName, Region, TestScope

E = TypeVar("E", bound=Enum)

MODULE_SYNONYMS: Dict[str, ModuleName] = {
    "payments": ModuleName.PAYMENT,
    "payment module": ModuleName.PAYMENT,
    "billing": ModuleName.PAYMENT,
    "wallets": ModuleName.WALLET,
    "checkouts": ModuleName.CHECKOUT,
    "cart": ModuleName.CHECKOUT,
    "logins": ModuleName.LOGIN,
    "log in": ModuleName.LOGIN,
    "sign in": ModuleName.LOGIN,
    "signin": ModuleName.LOGIN,
    "withdrawals": ModuleName.WITHDRAWAL,
    "withdraw": ModuleName.WITHDRAWAL,
    "payout": ModuleName.WITHDRAWAL,
    "payouts": ModuleName.WITHDRAWAL,
}

SCOPE_SYNONYMS: Dict[str, TestScope] = {
    "smoke test": TestScope.SMOKE,
    "smoke tests": TestScope.SMOKE,
    "sanity": TestScope.SMOKE,
    "regressions": TestScope.REGRESSION,
    "regression test": TestScope.REGRESSION,
    "regression tests": TestScope.REGRESSION,
    "full regression": TestScope.REGRESSION,
}

BROWSER_SYNONYMS: Dict[str, Browser] = {
    "google chrome": Browser.CHROME,
    "chrome browser": Browser.CHROME,
    "mozilla firefox": Browser.FIREFOX,
    "mozilla": Browser.FIREFOX,
    "ff": Browser.FIREFOX,
    "apple safari": Browser.SAFARI,
}

REGION_SYNONYMS: Dict[str, Region] = {
    "us": Region.US,
    "usa": Region.US,
    "u.s.": Region.US,
    "u.s.a.": Region.US,
    "united states": Region.US,
    "america": Region.US,
    "nevada": Region.US_NEVADA,
    "us nevada": Region.US_NEVADA,
    "us-nevada": Region.US_NEVADA,
    "nv": Region.US_NEVADA,
    "eu": Region.EU,
    "europe": Region.EU,
    "european union": Region.EU,
    "uk": Region.UK,
    "gb": Region.UK,
    "united kingdom": Region.UK,
    "great britain": Region.UK,
    "england": Region.UK,
}


def _resolve(
    value: Optional[str], enum_type: Type[E], synonyms: Dict[str, E]
) -> Optional[E]:
    """Return the controlled member for a raw value, or None if unsupported."""
    if value is None:
        return None
    candidate = " ".join(value.strip().lower().split())
    if not candidate:
        return None

    for member in enum_type:
        if candidate == member.value.lower():
            return member
    return synonyms.get(candidate)


def normalize_module(value: Optional[str]) -> Optional[ModuleName]:
    return _resolve(value, ModuleName, MODULE_SYNONYMS)


def normalize_scope(value: Optional[str]) -> Optional[TestScope]:
    return _resolve(value, TestScope, SCOPE_SYNONYMS)


def normalize_browser(value: Optional[str]) -> Optional[Browser]:
    return _resolve(value, Browser, BROWSER_SYNONYMS)


def normalize_region(value: Optional[str]) -> Optional[Region]:
    return _resolve(value, Region, REGION_SYNONYMS)
