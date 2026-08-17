from app.catalog import TestCatalog


def test_catalog_filters_known_payment_smoke_tests_for_chrome_in_us() -> None:
    catalog = TestCatalog.load_default()

    tests = catalog.filter(
        module="payment",
        scope="smoke",
        browser="chrome",
        region="US",
    )

    assert [test.id for test in tests] == ["PAY-001", "PAY-003"]
    assert all("chrome" in test.browsers for test in tests)
    assert all("US" in test.regions for test in tests)
