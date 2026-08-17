"""Browser-level tests for the local chat client.

Every API response is mocked at the network layer, so these run offline: no
backend, no vector store, and no OpenAI call is involved.
"""

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed"
)
sync_playwright = playwright_api.sync_playwright

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

CREATE_ROUTE = "**/api/v1/workflows"
DETAIL_ROUTE = "**/api/v1/workflows/WF-*"

# Fail fast: every wait in this file is against a mocked response that either
# arrives immediately or never will.
ACTION_TIMEOUT_MS = 5_000

COMPLETED = {
    "workflow_id": "WF-1001",
    "status": "completed",
    "summary": "1 of 2 test(s) failed.",
    "execution_id": "JOB-2001",
}

DETAIL = {
    "workflow_id": "WF-1001",
    "query": "Run payment smoke tests on Chrome in US",
    "status": "completed",
    "dry_run": False,
    "created_at": "2026-08-17T10:00:00Z",
    "updated_at": "2026-08-17T10:00:05Z",
    "intent": {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "environment": None,
        "confidence": 0.95,
        "missing_fields": [],
    },
    "retrieval": {"sources": ["HIST-001", "DOC-PAY-003"]},
    "plan": {
        "tests": [
            {
                "test_id": "PAY-003",
                "priority": 1,
                "risk_score": 0.9,
                "reasons": ["Matches the payment module and smoke scope"],
            }
        ]
    },
    "execution": {
        "execution_id": "JOB-2001",
        "status": "completed",
        "results": [
            {
                "test_id": "PAY-001",
                "status": "passed",
                "duration_ms": 900,
                "failure_reason": None,
            },
            {
                "test_id": "PAY-003",
                "status": "failed",
                "duration_ms": 1840,
                "failure_reason": "3DS redirect timeout",
            },
        ],
    },
    "analysis": {
        "summary": "1 of 2 tests failed.",
        "status": "ai_generated",
        "observations": ["PAY-003 failed after 1840ms"],
        "failures": [
            {
                "test_id": "PAY-003",
                "observed_facts": ["Timed out during the 3DS redirect"],
                "likely_cause": "Consistent with a 3DS redirect timeout",
                "confidence": 0.82,
                "evidence_source_ids": ["HIST-001"],
                "recommendations": ["Review gateway timeout configuration"],
            }
        ],
        "insufficient_evidence": False,
        "fallback_reason": None,
    },
    "timeline": [
        {
            "event_id": "EV-001",
            "step": "intent",
            "status": "intent_parsed",
            "occurred_at": "2026-08-17T10:00:01Z",
            "metadata": {},
        },
        {
            "event_id": "EV-002",
            "step": "analysis",
            "status": "analyzed",
            "occurred_at": "2026-08-17T10:00:04Z",
            "metadata": {},
        },
    ],
}


@pytest.fixture(scope="module")
def page_url():
    """Serve the frontend over HTTP.

    The page must run on an http origin: a file:// origin cannot resolve the
    relative /api/v1 fetch the client makes.
    """
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(FRONTEND)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser, page_url):
    context = browser.new_context()
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    created = context.new_page()
    created.goto(page_url)
    yield created
    context.close()


def _fulfil(route, status: int, payload: dict) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _mock(page, *, create_status=201, create_body=None, detail_body=None) -> dict:
    """Route API calls to canned responses and record what the page sent."""
    captured = {"requests": []}

    def handle(route, request):
        if request.method == "POST":
            captured["requests"].append(json.loads(request.post_data))
            _fulfil(route, create_status, create_body or COMPLETED)
        else:
            _fulfil(route, 200, detail_body or DETAIL)

    page.route(CREATE_ROUTE, handle)
    page.route(DETAIL_ROUTE, handle)
    return captured


def _submit(page, query: str, *, dry_run: bool = False) -> None:
    page.fill("#query", query)
    if dry_run:
        page.check("#dry-run")
    page.click("#send")


def test_the_page_loads_with_an_accessible_composer(page) -> None:
    assert page.title() == "Test Trigger — Local Test Assistant"
    assert page.get_by_label("Your testing request").is_visible()
    assert page.get_by_label("Dry run").is_visible()
    assert page.locator("#conversation").get_attribute("aria-live") == "polite"


def test_a_request_renders_the_workflow_outcome(page) -> None:
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")

    assistant = page.locator(".message.assistant").last
    assistant.get_by_text("completed").wait_for()
    assert "WF-1001" in assistant.inner_text()
    assert "1 of 2 test(s) failed." in assistant.inner_text()


def test_the_user_message_echoes_the_request(page) -> None:
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")

    assert "Run payment smoke tests" in page.locator(".message.user").last.inner_text()
    assert page.input_value("#query") == ""


def test_structured_stages_are_rendered(page) -> None:
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("Selected tests").wait_for()

    text = page.locator(".message.assistant").last.inner_text()
    assert "module: payment" in text
    assert "PAY-003" in text
    assert "Matches the payment module and smoke scope" in text
    assert "JOB-2001" in text
    assert "1840ms" in text


def test_observed_results_are_separated_from_inference(page) -> None:
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.locator(".inference").wait_for()

    # inner_text applies CSS casing, so compare case-insensitively.
    inference = page.locator(".inference").inner_text()
    assert "inferred — not confirmed" in inference.lower()
    assert "Consistent with a 3DS redirect timeout" in inference
    assert "evidence: HIST-001" in inference
    assert "FAILED" in page.locator(".result").last.inner_text()


def test_the_timeline_is_available_but_collapsed(page) -> None:
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")
    summary = page.get_by_text("Workflow timeline")
    summary.wait_for()

    assert not page.locator(".timeline").is_visible()
    summary.click()
    assert "intent" in page.locator(".timeline").inner_text()


def test_a_dry_run_is_sent_and_labelled(page) -> None:
    captured = _mock(
        page,
        create_body={
            "workflow_id": "WF-1001",
            "status": "dry_run_complete",
            "summary": "Dry run: 2 test(s) would run on chrome in US.",
            "execution_id": None,
        },
        detail_body={**DETAIL, "status": "dry_run_complete", "execution": None},
    )
    _submit(page, "Run payment smoke tests", dry_run=True)
    page.get_by_text("dry run complete").wait_for()

    assert captured["requests"][0]["dry_run"] is True
    assert "would run" in page.locator(".message.assistant").last.inner_text()


def test_a_clarification_asks_for_the_missing_fields(page) -> None:
    _mock(
        page,
        create_status=422,
        create_body={
            "error": {
                "code": "NEEDS_CLARIFICATION",
                "message": "the request did not state: browser, region",
                "workflow_id": "WF-1001",
                "details": [
                    {"field": "browser", "value": None},
                    {"field": "region", "value": None},
                ],
            }
        },
    )
    _submit(page, "Run some tests")
    page.get_by_text("Please include: browser, region.").wait_for()

    text = page.locator(".message.assistant").last.inner_text()
    assert "could not tell exactly what to run" in text
    assert "Traceback" not in text


def test_a_user_can_send_a_corrected_request_after_a_clarification(page) -> None:
    _mock(
        page,
        create_status=422,
        create_body={
            "error": {
                "code": "NEEDS_CLARIFICATION",
                "message": "missing fields",
                "workflow_id": "WF-1001",
                "details": [{"field": "browser", "value": None}],
            }
        },
    )
    _submit(page, "Run some tests")
    page.get_by_text("Please include: browser.").wait_for()

    assert page.locator("#send").is_enabled()
    assert page.input_value("#query") == ""


def test_a_policy_rejection_explains_why(page) -> None:
    _mock(
        page,
        create_status=422,
        create_body={
            "error": {
                "code": "NO_TESTS_SELECTED",
                "message": "No catalogued smoke test for login runs on chrome in US-Nevada.",
                "workflow_id": "WF-1001",
                "details": [
                    {"field": None, "value": "No catalogued test matched the request."}
                ],
            }
        },
    )
    _submit(page, "Run login smoke tests in Nevada")
    page.get_by_text("No catalogued smoke test").wait_for()

    text = page.locator(".message.assistant").last.inner_text()
    assert "rejected" in text.lower()
    assert "No catalogued test matched the request." in text


def test_a_service_error_is_reported_in_plain_language(page) -> None:
    _mock(
        page,
        create_status=503,
        create_body={
            "error": {
                "code": "EXECUTION_UNAVAILABLE",
                "message": "job JOB-2001 ended as failed",
                "workflow_id": "WF-1001",
                "details": [],
            }
        },
    )
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("The test runner did not finish this job.").wait_for()

    assert "The plan was kept" in page.locator(".message.assistant").last.inner_text()


def test_a_connection_failure_is_handled_without_crashing(page) -> None:
    page.route(CREATE_ROUTE, lambda route: route.abort())
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("could not reach the local backend").wait_for()

    assert page.locator("#send").is_enabled()
    assert page.locator(".message.pending").count() == 0


def test_an_empty_submission_does_nothing(page) -> None:
    captured = _mock(page)
    page.fill("#query", "   ")
    page.click("#send")

    assert captured["requests"] == []
    assert page.locator(".message.user").count() == 0


def test_a_pending_state_is_shown_while_working(page) -> None:
    def handle(route, request):
        if request.method == "POST":
            page.wait_for_timeout(400)
            _fulfil(route, 201, COMPLETED)
        else:
            _fulfil(route, 200, DETAIL)

    page.route(CREATE_ROUTE, handle)
    page.route(DETAIL_ROUTE, handle)
    _submit(page, "Run payment smoke tests on Chrome in US")

    page.locator(".message.pending").wait_for()
    assert page.locator("#send").is_disabled()
    page.get_by_text("1 of 2 test(s) failed.").wait_for()
    assert page.locator(".message.pending").count() == 0
    assert page.locator("#send").is_enabled()


def test_keyboard_users_can_submit_with_enter(page) -> None:
    captured = _mock(page)
    page.focus("#query")
    page.keyboard.type("Run payment smoke tests on Chrome in US")
    page.keyboard.press("Enter")
    page.get_by_text("1 of 2 test(s) failed.").wait_for()

    assert len(captured["requests"]) == 1


def test_shift_enter_inserts_a_newline_instead_of_sending(page) -> None:
    captured = _mock(page)
    page.focus("#query")
    page.keyboard.type("Run payment tests")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("on Chrome")

    assert captured["requests"] == []
    assert "\n" in page.input_value("#query")


def test_the_client_never_sends_a_credential(page) -> None:
    sent = []
    page.on("request", lambda request: sent.append(request))
    _mock(page)
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("1 of 2 test(s) failed.").wait_for()

    for request in sent:
        headers = {key.lower() for key in request.all_headers()}
        assert "authorization" not in headers
        assert "openai" not in (request.post_data or "").lower()

    storage = page.evaluate("() => JSON.stringify(window.localStorage)")
    assert "sk-" not in storage
    assert page.evaluate("() => document.body.innerHTML").count("OPENAI") == 0


def test_the_bundle_contains_no_provider_call(page) -> None:
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "openai.com" not in source
    assert "OPENAI_API_KEY" not in source
    assert "chroma" not in source.lower()


def test_a_detail_failure_still_renders_the_outcome(page) -> None:
    def handle(route, request):
        if request.method == "POST":
            _fulfil(route, 201, COMPLETED)
        else:
            route.abort()

    page.route(CREATE_ROUTE, handle)
    page.route(DETAIL_ROUTE, handle)
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("1 of 2 test(s) failed.").wait_for()

    assert "WF-1001" in page.locator(".message.assistant").last.inner_text()


def test_a_fallback_analysis_is_labelled_as_deterministic(page) -> None:
    _mock(
        page,
        detail_body={
            **DETAIL,
            "analysis": {
                "summary": "1 of 2 test(s) failed.",
                "status": "fallback",
                "observations": ["PAY-003 failed in 1840ms: 3DS redirect timeout"],
                "failures": [],
                "insufficient_evidence": True,
                "fallback_reason": "analysis provider failed: timed out",
            },
        },
    )
    _submit(page, "Run payment smoke tests on Chrome in US")
    page.get_by_text("Deterministic summary").wait_for()

    text = page.locator(".message.assistant").last.inner_text()
    assert "AI analysis unavailable" in text
    assert page.locator(".inference").count() == 0
