"""Probe — manually exercise the Ninja API for debugging.

Usage from inside the ingest container:

    docker exec -it operations-ingest python -m ingest.probe <path> [options]

Examples:

    # Single GET, top-level shape + first record
    docker exec operations-ingest python -m ingest.probe /organizations

    # Cursor pagination walk — confirms whether cursor.name advances
    docker exec operations-ingest python -m ingest.probe \
        /queries/os-patch-installs --pages 3 --page-size 2

    # Inspect a custom-fields response in full
    docker exec operations-ingest python -m ingest.probe \
        /queries/custom-fields --pages 1 --page-size 1 --full

    # Pass extra query params (repeatable)
    docker exec operations-ingest python -m ingest.probe \
        /devices-detailed --param 'df=class in (WINDOWS_WORKSTATION)' --pages 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from ingest.config import settings
from ingest.ninja_client import NinjaClient


def _truncate(s: str, limit: int = 800) -> str:
    return s if len(s) <= limit else s[:limit] + f"\n... [truncated, full was {len(s)} chars]"


def _print_dict_response(resp: dict[str, Any], full: bool) -> str | None:
    """Print a dict response. Returns the next cursor name (or None)."""
    cursor_obj = resp.get("cursor") or {}
    print(f"  Type: dict")
    print(f"  Top-level keys: {list(resp.keys())}")

    # Show sizes of all top-level array values — catches Ninja's
    # endpoint-specific data-key naming (results, activities, data, etc.)
    array_keys = [k for k, v in resp.items() if isinstance(v, list)]
    if array_keys:
        print("  Top-level arrays:")
        for k in array_keys:
            print(f"    - {k}: {len(resp[k])} items")

    if cursor_obj:
        print(f"  Cursor: {json.dumps(cursor_obj)}")
    else:
        print(f"  Cursor: <none>")

    # Pick the most-populated array as the "results" surface for sampling.
    biggest_arr = max(array_keys, key=lambda k: len(resp[k])) if array_keys else None
    results = resp.get(biggest_arr) if biggest_arr else []
    if results:
        first = results[0]
        if isinstance(first, dict):
            print(f"  First {biggest_arr} item keys: {list(first.keys())}")
        if full:
            print(f"  {biggest_arr} sample (first 3):")
            print(_truncate(json.dumps(results[:3], indent=2, default=str), 4000))
        else:
            print(f"  First {biggest_arr}: {_truncate(json.dumps(first, indent=2, default=str))}")
    return cursor_obj.get("name") if isinstance(cursor_obj, dict) else None


def _print_list_response(resp: list, full: bool) -> str | int | None:
    """Print a list response. Returns the last item's id (for after-pagination)."""
    print(f"  Type: list of {len(resp)} items")
    if not resp:
        return None
    first = resp[0]
    if isinstance(first, dict):
        print(f"  Item keys: {list(first.keys())}")
    if full:
        print("  Items sample (first 3):")
        print(_truncate(json.dumps(resp[:3], indent=2, default=str), 4000))
    else:
        print(f"  First item: {_truncate(json.dumps(first, indent=2, default=str))}")
    last = resp[-1]
    return last.get("id") if isinstance(last, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the Ninja API")
    parser.add_argument("path", help="API path, e.g. /organizations")
    parser.add_argument("--page-size", type=int, default=2)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument(
        "--param", action="append", default=[],
        help="Extra query param key=value (repeatable)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Print fuller sample (first 3 records, more chars)",
    )
    args = parser.parse_args()

    # Quiet httpx INFO logging so probe output isn't noisy.
    logging.basicConfig(level="WARNING", format="%(levelname)s %(name)s %(message)s")

    extra_params: dict[str, Any] = {}
    for p in args.param:
        if "=" not in p:
            print(f"--param needs key=value, got: {p}", file=sys.stderr)
            return 1
        k, v = p.split("=", 1)
        extra_params[k] = v

    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        next_cursor: Any = None
        for page in range(1, args.pages + 1):
            params = dict(extra_params)
            params["pageSize"] = args.page_size
            if next_cursor is not None:
                # cursor-style queries use "cursor", list endpoints use "after"
                if isinstance(next_cursor, str):
                    params["cursor"] = next_cursor
                else:
                    params["after"] = next_cursor

            print(f"\n=== Page {page} ===")
            print(f"  Request: GET {args.path} {params}")
            resp = client.get(args.path, params)

            if isinstance(resp, dict):
                next_cursor = _print_dict_response(resp, args.full)
            elif isinstance(resp, list):
                next_cursor = _print_list_response(resp, args.full)
            else:
                print(f"  Type: {type(resp).__name__}")
                print(f"  Value: {_truncate(repr(resp))}")
                next_cursor = None

            if next_cursor is None:
                print("\n[no next cursor — stopping]")
                break

    return 0


if __name__ == "__main__":
    sys.exit(main())
