"""Probe /v2/activities — figure out the right filter + pagination params.

Run from inside the container:
    docker exec -it ninja-ingest python -m ingest.probe_activities
"""

from __future__ import annotations

import json
import logging
import sys

from ingest.config import settings
from ingest.ninja_client import NinjaClient


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
        r = c.get("/activities", {"pageSize": 5})
        print("count:", len(r.get("activities", [])))
        if r.get("activities"):
            sample = r["activities"][0]
            print("First record keys:", sorted(sample.keys()))
            print("First record:")
            print(json.dumps(sample, indent=2, default=str)[:1500])

        print("\n=== Filter activityType=PATCH_MANAGEMENT ===")
        r = c.get("/activities", {"pageSize": 5, "activityType": "PATCH_MANAGEMENT"})
        print("count:", len(r.get("activities", [])))
        if r.get("activities"):
            print("First sample:")
            print(json.dumps(r["activities"][0], indent=2, default=str)[:1500])

        print("\n=== Filter class=PATCH_MANAGEMENT ===")
        r = c.get("/activities", {"pageSize": 5, "class": "PATCH_MANAGEMENT"})
        print("count:", len(r.get("activities", [])))

        print("\n=== Pagination tests ===")
        r1 = c.get("/activities", {"pageSize": 3})
        ids1 = [a["id"] for a in r1.get("activities", [])]
        print(f"latest 3: {ids1}")
        if not ids1:
            print("(no activities returned, can't test pagination)")
            return 0

        anchor = ids1[-1]
        # Walk OLDER — try various param names
        for param in ("before", "older", "olderThan", "olderTan"):
            try:
                r = c.get("/activities", {"pageSize": 3, param: anchor})
                ids = [a["id"] for a in r.get("activities", [])]
                marker = "  (older✓)" if ids and ids[0] < anchor else ""
                print(f"  {param}={anchor}: {ids}{marker}")
            except Exception as e:
                print(f"  {param}={anchor}: ERROR {e}")

        # Walk NEWER — for incremental ingest
        target = anchor - 100
        for param in ("after", "newer", "newerThan"):
            try:
                r = c.get("/activities", {"pageSize": 10, param: target})
                ids = [a["id"] for a in r.get("activities", [])]
                marker = "  (newer✓)" if ids and ids[0] > target else ""
                print(f"  {param}={target}: {ids}{marker}")
            except Exception as e:
                print(f"  {param}={target}: ERROR {e}")

        print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
