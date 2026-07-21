"""Shared observation normalization and current/history write primitive.

Connector-specific code supplies already-normalized row dictionaries.  Keeping
material hashing here ensures all writers use the same policy and hash version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from ingest import db

MATERIAL_HASH_VERSION = 1
VOLATILE_FIELDS = frozenset({
    "last_seen_at", "last_contact", "is_online", "offline",
    "hostStateChangeDate", "lastActive", "last_boot_time_at",
})


def material_projection(canonical: dict[str, Any]) -> dict[str, Any]:
    return {k: canonical[k] for k in sorted(canonical) if k not in VOLATILE_FIELDS}


def material_hash(canonical: dict[str, Any]) -> bytes:
    payload = json.dumps(material_projection(canonical), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).digest()


def prepare_observation(row: dict[str, Any]) -> dict[str, Any]:
    canonical = row.get("canonical_data") or {}
    row = dict(row)
    row["material_hash"] = material_hash(canonical)
    row["material_data"] = material_projection(canonical)
    row["hash_algorithm_version"] = MATERIAL_HASH_VERSION
    return row


def prepare_batch(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [prepare_observation(row) for row in rows]


def write_current_rows(cur: Any, rows: Iterable[dict[str, Any]]) -> int:
    """Upsert prepared rows into the current-state table.

    Connector adapters remain responsible for resolving foreign keys and
    snapshot metadata; this primitive owns only the stable column mapping.
    """
    prepared = prepare_batch(rows)
    if not prepared:
        return 0
    columns = (
        "observation_id", "tenant_id", "source_binding_id", "collector_instance_id",
        "client_id", "device_id", "entity_type", "parent_source_key", "entity_key",
        "platform", "subplatform", "observed_at", "last_seen_at", "last_received_at",
        "active", "withdrawn_at", "snapshot_scope", "last_snapshot_run_id",
        "raw_data", "canonical_data", "raw_hash", "material_hash",
        "hash_algorithm_version", "batch_id", "collector_version", "schema_version",
    )
    shaped = [{key: row.get(key) for key in columns} for row in prepared]
    return db.upsert(
        cur,
        "operations.entity_observation_current",
        shaped,
        conflict_keys=["tenant_id", "source_binding_id", "entity_type", "parent_source_key", "entity_key"],
        update_cols=[
            "client_id", "device_id", "platform", "subplatform", "observed_at",
            "last_seen_at", "last_received_at", "active", "withdrawn_at",
            "snapshot_scope", "last_snapshot_run_id", "raw_data", "canonical_data",
            "raw_hash", "material_hash", "hash_algorithm_version", "batch_id",
            "collector_version", "schema_version",
        ],
    )
