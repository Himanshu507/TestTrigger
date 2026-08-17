"""Example CLI client for the Test Trigger API.

Submits and inspects workflows over HTTP exactly as the local chat UI does, so
a reviewer can exercise every documented scenario without writing backend code.

Usage:
    uv run python scripts/client.py run "Run payment smoke tests on Chrome in US"
    uv run python scripts/client.py run "..." --dry-run
    uv run python scripts/client.py show WF-1001
    uv run python scripts/client.py events WF-1001
    uv run python scripts/client.py cancel WF-1001
    uv run python scripts/client.py health

The client never sends or receives an API key; model calls stay in the backend.
"""

import argparse
import json
import sys
import uuid
from typing import Any, Dict, Optional

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
TIMEOUT_SECONDS = 120.0


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> int:
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        response = httpx.request(
            method,
            f"{base_url}{path}",
            json=body,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as error:
        print(f"Could not reach {base_url}: {error}", file=sys.stderr)
        return 2

    _print(response)
    return 0 if response.is_success else 1


def _print(response: httpx.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        print(response.text)
        return

    print(f"HTTP {response.status_code}")
    print(json.dumps(payload, indent=2))

    error = payload.get("error") if isinstance(payload, dict) else None
    if error:
        print(f"\n{error['code']}: {error['message']}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Test Trigger API client")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Submit a testing request")
    run.add_argument("query")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--idempotency-key",
        help="Reuse a key to replay a prior request instead of running it again.",
    )

    for name, help_text in (
        ("show", "Inspect a workflow"),
        ("events", "Read the workflow timeline"),
        ("cancel", "Cancel an active job"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("workflow_id")

    commands.add_parser("health", help="Report dependency readiness")

    args = parser.parse_args(argv)

    if args.command == "run":
        return _request(
            args.base_url,
            "POST",
            "/api/v1/workflows",
            body={"query": args.query, "dry_run": args.dry_run},
            idempotency_key=args.idempotency_key or str(uuid.uuid4()),
        )
    if args.command == "show":
        return _request(args.base_url, "GET", f"/api/v1/workflows/{args.workflow_id}")
    if args.command == "events":
        return _request(
            args.base_url, "GET", f"/api/v1/workflows/{args.workflow_id}/events"
        )
    if args.command == "cancel":
        return _request(
            args.base_url, "POST", f"/api/v1/workflows/{args.workflow_id}/cancel"
        )
    return _request(args.base_url, "GET", "/health")


if __name__ == "__main__":
    raise SystemExit(main())
