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


_NAMESPACES = {
    "Ninja": ("device", "organization"),
    "SentinelOne": ("agent", "site"),
    "ScreenConnect": ("access-session", "source-instance"),
    "LogMeIn": ("host", "group"),
    "Hudu": ("asset", "company"),
}


def _stable_identity(source_name: str, entity_type: str, entity_key: str) -> tuple[str, str]:
    try:
        record_namespace, container_namespace = _NAMESPACES[source_name]
    except KeyError as exc:
        raise ValueError(f"no stable namespace rule for source {source_name!r}") from exc
    if entity_type == "org":
        external_id = "self" if source_name == "ScreenConnect" else entity_key
        return container_namespace, external_id
    return record_namespace, entity_key


def run(*, batch_size: int = 1000, after: str = "", dry_run: bool = False) -> int:
    copied = 0
    cursor = after
    while True:
        with db.transaction() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                """
                SELECT o.observation_id, o.tenant_id, o.source_binding_id,
                       sb.source_instance_id, s.name AS source_name,
                       o.collector_instance_id, o.client_id, o.device_id,
                       o.entity_type, o.entity_key, o.platform, o.subplatform,
                       o.observed_at, o.raw_data, o.canonical_data, o.batch_id,
                       o.collector_version, o.schema_version
                  FROM operations.entity_observations o
                  JOIN operations.source_bindings sb ON sb.id = o.source_binding_id
                  JOIN operations.source_instances si ON si.id = sb.source_instance_id
                  JOIN operations.sources s ON s.id = si.source_id
                 WHERE o.observation_id::text > %s
                 ORDER BY o.observation_id
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
                    namespace, external_id = _stable_identity(
                        row.pop("source_name"), row["entity_type"], row["entity_key"]
                    )
                    row["last_seen_binding_id"] = row["source_binding_id"]
                    row["external_namespace"] = namespace
                    row["parent_external_namespace"] = ""
                    row["parent_external_id"] = ""
                    row["external_id"] = external_id
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
