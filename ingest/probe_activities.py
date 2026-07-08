"""Probe /v2/activities — figure out the right filter + pagination params.

Run from inside the container:
    docker exec -it operations-ingest python -m ingest.probe_activities

Each test is wrapped in try/except — a single 400 / 500 won't abort
the rest. Output marks what worked (✓), what didn't (✗), what was
silently ignored (~).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import httpx

from ingest.config import settings
from ingest.ninja_client import NinjaClient


def _safe_get(c: NinjaClient, params: dict[str, Any]) -> tuple[list[dict] | None, str]:
    """Return (activities, status_text). activities=None on error."""
    try:
        r = c.get("/activities", params)
        return r.get("activities", []), "ok"
    except httpx.HTTPStatusError as e:
        return None, f"HTTP {e.response.status_code}"
    except Exception as e:
        return None, f"err {type(e).__name__}: {e}"


def _ids(records: list[dict] | None) -> list[int]:
    return [r["id"] for r in (records or [])]


def main() -> int:
    logging.basicConfig(level="WARNING", format="%(levelname)s %(name)s %(message)s")

    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as c:

        print("\n=== Latest 5 activities (no filter) ===")
        records, status = _safe_get(c, {"pageSize": 5})
        print(f"status: {status}, count: {len(records or [])}")
        if records:
            sample = records[0]
            print(f"keys: {sorted(sample.keys())}")
            print(f"sample: {json.dumps(sample, default=str)[:400]}")
            anchor_id = records[-1]["id"]
        else:
            print("aborting — endpoint didn't return")
            return 1

        # ── Filter variants ────────────────────────────────────────
        print("\n=== Filter variants ===")
        print("(✓ = filter worked, returned different/fewer records;"
              " ~ = silently ignored, returned same as no filter;"
              " ✗ = rejected)")

        baseline = set(_ids(records))

        filter_tests = [
            {"activityType": "PATCH_MANAGEMENT"},
            {"activityType": "SYSTEM"},
            {"activityType": "ALERT"},
            {"type": "Monitor"},
            {"type": "PATCH_MANAGEMENT"},
            {"statusCode": "PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED"},
            {"statusCode": "USER_LOGGED_IN"},
            {"status": "Software Updated"},
            {"nodeId": records[0]["deviceId"]},
            {"deviceId": records[0]["deviceId"]},
            {"sourceConfigUid": "PATCH_MANAGEMENT"},
            {"seriesUid": "PATCH_MANAGEMENT"},
            {"lang": "en"},  # sanity — should be ignored, not crash
        ]
        for params in filter_tests:
            params_with_size = {**params, "pageSize": 5}
            recs, status = _safe_get(c, params_with_size)
            tag = "?"
            if recs is None:
                tag = "✗"
            elif not recs:
                tag = "✓(empty)"
            elif set(_ids(recs)) == baseline:
                tag = "~"
            else:
                tag = "✓"
            print(f"  {tag} {params}: status={status} count={len(recs or [])} ids={_ids(recs)[:3]}")

        # ── Pagination variants ────────────────────────────────────
        print("\n=== Pagination tests ===")
        print(f"anchor (last id in latest 5): {anchor_id}")

        # Walk OLDER
        for param in ("before", "older", "olderThan", "to"):
            recs, status = _safe_get(c, {"pageSize": 3, param: anchor_id})
            ids = _ids(recs)
            tag = ("✓ older" if ids and all(i < anchor_id for i in ids)
                   else "~ same" if ids and set(ids) == {anchor_id - i for i in range(3)} else "?")
            if recs is None:
                tag = "✗"
            elif ids and all(i < anchor_id for i in ids):
                tag = "✓ (walks older)"
            elif not ids:
                tag = "✓(empty)"
            elif set(ids) == baseline:
                tag = "~ ignored"
            else:
                tag = "? "
            print(f"  {tag}  {param}={anchor_id}: status={status} ids={ids}")

        # Walk NEWER (this is the one we need for incremental ingest)
        target = anchor_id - 200
        print(f"\nlooking for activities NEWER than {target}:")
        for param in ("after", "newer", "newerThan", "from"):
            recs, status = _safe_get(c, {"pageSize": 10, param: target})
            ids = _ids(recs)
            if recs is None:
                tag = "✗"
            elif not ids:
                tag = "✓(empty)"
            elif ids and all(i > target for i in ids):
                tag = "✓ (walks newer)"
            elif set(ids) == baseline:
                tag = "~ ignored"
            else:
                tag = "?"
            print(f"  {tag}  {param}={target}: status={status} ids={ids[:5]}")

        print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
