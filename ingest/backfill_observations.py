"""Resumable legacy observation backfill.

This module is intentionally an operator-invoked tool, not a Django migration.
It copies bounded batches and can be restarted safely by observation_id.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from ingest import db
from ingest.observations import write_current_rows


def run(*, batch_size: int = 1000, after: str = "", dry_run: bool = False) -> int:
    copied = 0
    cursor = after
    while True:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT observation_id, tenant_id, source_binding_id,
                       collector_instance_id, client_id, device_id,
                       entity_type, entity_key, platform, subplatform,
                       observed_at, raw_data, canonical_data, batch_id,
                       collector_version, schema_version
                  FROM operations.entity_observations
                 WHERE observation_id::text > %s
                 ORDER BY observation_id
                 LIMIT %s
                """,
                (cursor, batch_size),
            )
            rows = [dict(zip((d.name for d in cur.description), row)) for row in cur.fetchall()]
            if not rows:
                return copied
            if not dry_run:
                now = datetime.now(timezone.utc)
                for row in rows:
                    row["parent_source_key"] = ""
                    row["last_seen_at"] = row["observed_at"]
                    row["last_received_at"] = now
                    row["active"] = True
                    row["withdrawn_at"] = None
                    row["snapshot_scope"] = "backfill"
                    row["last_snapshot_run_id"] = None
                    row["raw_hash"] = None
                write_current_rows(cur, rows)
            copied += len(rows)
            cursor = str(rows[-1]["observation_id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--after", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps({"copied": run(**vars(args))}))
