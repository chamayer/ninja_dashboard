"""Dashboard JSON export — fetch each provisioned Metabase dashboard
via the API and write the full JSON to disk for version control.

The bootstrap regenerates dashboards from code, but any operator-side
tweaks (column widths, custom filter values, manually added cards)
live only in Metabase's Postgres state. This tool snapshots them so
the snapshots can be committed to git or backed up.

Operator runs (inside the ingest container):
    docker exec operations-ingest python -m ingest.metabase_export \\
        --user admin@example.com --password-file /run/secrets/mb

Defaults:
- Output directory: ./metabase/dashboards/ (relative to repo root —
  inside the container that's /app/metabase/dashboards/).
- Collection: same constant used by the bootstrap (COLLECTION_NAME).
- Filenames: slugified dashboard name + ".json".

Each output file contains the full dashboard payload returned by
GET /api/dashboard/<id>, pretty-printed (indent=2) so diffs are
reviewable. Re-running overwrites; commit/review/discard as usual.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import httpx

from ingest.metabase_bootstrap import (
    COLLECTION_NAME,
    _authenticate,
    _resolve_password,
    _upsert_collection,
)

log = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Turn a Metabase dashboard name into a filesystem-friendly slug.
    "Ninja — Patch Command Center" → "ninja-patch-command-center"."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _list_dashboards_in_collection(
    client: httpx.Client, col_id: int,
) -> list[dict]:
    """Return all non-archived dashboards in the given collection."""
    r = client.get("/api/dashboard")
    r.raise_for_status()
    payload = r.json()
    # Some Metabase versions wrap in {data: [...]}, others return a list
    items = (
        payload["data"] if isinstance(payload, dict) and "data" in payload
        else payload
    )
    return [
        d for d in items
        if d.get("collection_id") == col_id and not d.get("archived")
    ]


def _fetch_dashboard_full(client: httpx.Client, dash_id: int) -> dict:
    r = client.get(f"/api/dashboard/{dash_id}")
    r.raise_for_status()
    return r.json()


def export(
    url: str, user: str, password: str, out_dir: Path,
) -> list[Path]:
    """Authenticate, find each dashboard in the Ninja collection, and
    write its JSON to out_dir. Returns the list of files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with httpx.Client(base_url=url, timeout=60) as client:
        _authenticate(client, user, password)
        col_id = _upsert_collection(client, COLLECTION_NAME)
        dashboards = _list_dashboards_in_collection(client, col_id)
        log.info(
            "Found %d dashboards in collection %r",
            len(dashboards), COLLECTION_NAME,
        )
        for d in dashboards:
            name = d.get("name") or f"dashboard-{d['id']}"
            full = _fetch_dashboard_full(client, int(d["id"]))
            path = out_dir / f"{_slugify(name)}.json"
            path.write_text(
                json.dumps(full, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            log.info("  wrote %s (%d bytes)", path, path.stat().st_size)
            written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Metabase dashboards to JSON for version control."
    )
    parser.add_argument(
        "--url", default="http://metabase:3000",
        help="Metabase base URL (default: http://metabase:3000)",
    )
    parser.add_argument(
        "--user", required=True, help="Metabase admin email",
    )
    parser.add_argument(
        "--password",
        help="Metabase admin password (avoid — visible in process list)",
    )
    parser.add_argument(
        "--password-file",
        help="Read password from file (plain or .env-style KEY=value).",
    )
    parser.add_argument(
        "--password-file-key", default="MB_ADMIN_PASS",
        help="Env-var key inside --password-file (default: MB_ADMIN_PASS).",
    )
    parser.add_argument(
        "--out-dir", default="metabase/dashboards",
        help="Output directory (default: ./metabase/dashboards).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(message)s",
    )

    password = _resolve_password(args)
    out_dir = Path(args.out_dir)
    files = export(args.url, args.user, password, out_dir)
    print()
    print(f"Exported {len(files)} dashboard(s) to {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
