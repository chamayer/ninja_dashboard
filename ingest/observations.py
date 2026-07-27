"""Shared observation normalization and current/history write primitive.

Connector-specific code supplies already-normalized row dictionaries.  Keeping
material hashing here ensures all writers use the same policy and hash version.

Correctness contract (per ADR-0007 §Heartbeat, §SCD-2, §Absence):

- Per-tuple advisory lock covers both existing and brand-new identities;
  `SELECT ... FOR UPDATE` alone cannot lock a row that does not exist yet.
- Rows whose incoming `observed_at` is not strictly newer than the currently
  stored `observed_at` are dropped BEFORE any history mutation, so an older
  or duplicate-timestamp snapshot cannot open a phantom history interval.
- Resolved `device_id` / `client_id` on the existing current row are
  preserved when the incoming row is NULL — both in Python (before shaping)
  and in the SQL upsert (COALESCE), so a connector NULL can never clear a
  resolver-populated value.
- The closing `_history.last_seen_at` on a material transition is the prior
  current row's last confirmed observation time, not the incoming row's
  `last_seen_at` (which is the *new* state's confirmation).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from psycopg.types.json import Json

MATERIAL_HASH_VERSION = 1
VOLATILE_FIELDS = frozenset({
    "last_seen_at", "last_contact", "is_online", "offline",
    "hostStateChangeDate", "lastActive", "last_boot_time_at",
    "power_state",
})

# Columns written to entity_observation_current. Kept as a module constant so
# the bespoke upsert SQL and the row-shaping loop stay in lockstep.
_CURRENT_COLUMNS: tuple[str, ...] = (
    "observation_id", "tenant_id", "source_binding_id", "collector_instance_id",
    "client_id", "device_id", "entity_type", "parent_source_key", "entity_key",
    "platform", "subplatform", "observed_at", "last_seen_at", "last_received_at",
    "active", "withdrawn_at", "snapshot_scope", "last_snapshot_run_id",
    "raw_data", "canonical_data", "raw_hash", "material_hash",
    "hash_algorithm_version", "batch_id", "collector_version", "schema_version",
)

# Columns updated with EXCLUDED.c on conflict. Matches the pre-hardening
# update set minus (a) the 5 identity keys — carried by ON CONFLICT — and
# (b) client_id/device_id, which use COALESCE to preserve post-hoc resolver
# writes against fresh connector NULLs. observation_id and
# collector_instance_id are intentionally excluded so per-identity primary
# key stays stable across heartbeats (identity_candidates FK depends on it).
_CURRENT_UPDATE_COLUMNS: tuple[str, ...] = (
    "platform", "subplatform", "observed_at", "last_seen_at",
    "last_received_at", "active", "withdrawn_at", "snapshot_scope",
    "last_snapshot_run_id", "raw_data", "canonical_data", "raw_hash",
    "material_hash", "hash_algorithm_version", "batch_id",
    "collector_version", "schema_version",
)


def material_projection(canonical: dict[str, Any]) -> dict[str, Any]:
    return {k: canonical[k] for k in sorted(canonical) if k not in VOLATILE_FIELDS}


def material_hash(canonical: dict[str, Any]) -> bytes:
    payload = json.dumps(material_projection(canonical), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).digest()


def prepare_observation(row: dict[str, Any]) -> dict[str, Any]:
    canonical = row.get("canonical_data") or {}
    if hasattr(canonical, "obj"):
        canonical = canonical.obj
    if not isinstance(canonical, dict):
        canonical = {}
    row = dict(row)
    raw_data = row.get("raw_data")
    if isinstance(raw_data, dict):
        row["raw_data"] = Json(raw_data)
    row["canonical_data"] = Json(canonical)
    row["material_hash"] = material_hash(canonical)
    row["material_data"] = Json(material_projection(canonical))
    row["hash_algorithm_version"] = MATERIAL_HASH_VERSION
    return row


def prepare_batch(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [prepare_observation(row) for row in rows]


def _identity_tuple(row: dict[str, Any]) -> tuple:
    """Canonical 5-column identity tuple for sort and locking.

    parent_source_key is normalized to '' for top-level entities so tuples
    sort deterministically alongside child-entity rows.
    """
    return (
        row["tenant_id"],
        str(row["source_binding_id"]),
        row["entity_type"],
        row.get("parent_source_key") or "",
        row["entity_key"],
    )


def _identity_lock_key(row: dict[str, Any]) -> str:
    """Deterministic string fed to pg_advisory_xact_lock via hashtextextended.

    Two batches that share some — but not all — identity tuples must acquire
    locks in the same order. The caller sorts by _identity_tuple before
    iterating, and each iteration locks on this string.
    """
    return "|".join(str(part) for part in _identity_tuple(row))


def write_current_rows(cur: Any, rows: Iterable[dict[str, Any]]) -> int:
    """Upsert prepared rows into the current-state table.

    Per ADR-0007 hardening, each row is processed under a transaction-scoped
    advisory lock keyed on the identity tuple, so absent-row races between
    concurrent writers are serialized. For each locked identity:

    1. Read prior state under SELECT ... FOR UPDATE (no-op if the row does
       not exist — the advisory lock is the guard for that case).
    2. Out-of-order guard: drop the incoming row entirely if its observed_at
       is not strictly newer than the stored observed_at. Equal timestamps
       are treated as stale to prevent zero-length SCD-2 intervals.
    3. Determine whether material or presence state changed; if so, queue
       the row for `write_history_changes` and carry the prior
       last_seen_at side-band for the close.
    4. Preserve resolved client_id / device_id (never overwrite non-NULL
       with NULL).
    5. Bespoke UPSERT with COALESCE on the resolved-ID columns and a
       belt-and-braces WHERE observed_at < EXCLUDED.observed_at predicate.

    Returns the number of rows accepted (skipped out-of-order rows are not
    counted). Callers that need "rows in batch" should track that
    separately from the input.
    """
    prepared = prepare_batch(rows)
    if not prepared:
        return 0

    # Deterministic order per identity tuple — prevents deadlocks between
    # concurrent batches that share some but not all identities.
    prepared.sort(key=_identity_tuple)

    changed_for_history: list[dict[str, Any]] = []
    to_upsert: list[dict[str, Any]] = []

    for row in prepared:
        # Normalize parent_source_key once so downstream code can rely on it.
        row["parent_source_key"] = row.get("parent_source_key") or ""

        # (1) Transaction-scoped identity lock covers new tuples too.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (_identity_lock_key(row),),
        )

        # (2) Read prior state under FOR UPDATE (no-op if not present).
        cur.execute(
            """
            SELECT observed_at, material_hash, active, client_id, device_id,
                   last_seen_at
              FROM operations.entity_observation_current
             WHERE tenant_id = %s AND source_binding_id = %s
               AND entity_type = %s AND parent_source_key = %s
               AND entity_key = %s
             FOR UPDATE
            """,
            (row["tenant_id"], row["source_binding_id"], row["entity_type"],
             row["parent_source_key"], row["entity_key"]),
        )
        prev = cur.fetchone()

        # (3) Out-of-order / equal-timestamp guard runs BEFORE any history
        # mutation so an older or duplicate snapshot cannot open a phantom
        # SCD-2 interval.
        if prev is not None and prev[0] is not None \
                and row["observed_at"] <= prev[0]:
            continue

        # (4) Material or presence transition detection.
        is_new = prev is None
        material_changed = (
            not is_new
            and (prev[1] != row["material_hash"]
                 or prev[2] != row.get("active", True))
        )
        if is_new or material_changed:
            # Side-band the prior last_seen_at so write_history_changes can
            # close the open version at its true last-confirmed time (not
            # the new observation's time).
            row["_prior_last_seen_at"] = None if is_new else prev[5]
            changed_for_history.append(row)

        # (5) Resolved-ID preservation — mirrored in the SQL COALESCE below
        # as defence in depth, but doing it here keeps the row shape truthful
        # before shaping / logging.
        if prev is not None:
            if row.get("client_id") is None and prev[3] is not None:
                row["client_id"] = prev[3]
            if row.get("device_id") is None and prev[4] is not None:
                row["device_id"] = prev[4]

        to_upsert.append(row)

    # History write batches all queued changes in one call. Failures here
    # roll the whole caller transaction back, so we never leave overlapping
    # intervals.
    if changed_for_history:
        write_history_changes(cur, changed_for_history)

    if not to_upsert:
        return 0

    return _upsert_current(cur, to_upsert)


def _upsert_current(cur: Any, rows: list[dict[str, Any]]) -> int:
    """Bespoke observation-current upsert.

    Diverges from `db.upsert()` in two ways required by ADR-0007 hardening:
      - COALESCE on client_id / device_id preserves post-hoc resolver /
        merge writes against a fresh connector NULL.
      - WHERE entity_observation_current.observed_at < EXCLUDED.observed_at
        is a belt-and-braces guard against any bypass of the Python
        out-of-order check.

    Runs `executemany` to preserve bulk performance.
    """
    if not rows:
        return 0

    shaped = [{key: row.get(key) for key in _CURRENT_COLUMNS} for row in rows]
    cols_sql = ", ".join(_CURRENT_COLUMNS)
    placeholders_sql = ", ".join(f"%({c})s" for c in _CURRENT_COLUMNS)

    update_pieces = [
        "client_id = COALESCE(EXCLUDED.client_id, "
        "operations.entity_observation_current.client_id)",
        "device_id = COALESCE(EXCLUDED.device_id, "
        "operations.entity_observation_current.device_id)",
    ]
    for c in _CURRENT_UPDATE_COLUMNS:
        update_pieces.append(f"{c} = EXCLUDED.{c}")
    update_sql = ", ".join(update_pieces)

    stmt = (
        f"INSERT INTO operations.entity_observation_current ({cols_sql}) "
        f"VALUES ({placeholders_sql}) "
        "ON CONFLICT (tenant_id, source_binding_id, entity_type, "
        "parent_source_key, entity_key) DO UPDATE SET "
        f"{update_sql} "
        "WHERE operations.entity_observation_current.observed_at "
        "< EXCLUDED.observed_at"
    )
    cur.executemany(stmt, shaped)
    return cur.rowcount


def write_history_changes(cur: Any, rows: Iterable[dict[str, Any]]) -> int:
    """Close the currently open SCD-2 version and insert a new open one.

    Callers pass rows already determined to be changed (new identity, or a
    material / presence transition). The update and insert run in the
    caller's transaction so a failed batch cannot leave overlapping intervals
    or a stranded close.

    The closing `last_seen_at` uses the prior current row's last confirmed
    observation time (`_prior_last_seen_at`), side-banded by
    `write_current_rows`. Falling back to the incoming row's `last_seen_at`
    would attribute the closing time to the new state — semantically wrong.
    """
    prepared = prepare_batch(rows)
    if not prepared:
        return 0
    for row in prepared:
        identity = (
            row["tenant_id"], row["source_binding_id"], row["entity_type"],
            row.get("parent_source_key") or "", row["entity_key"],
        )
        prior_last_seen = row.get("_prior_last_seen_at") or row["observed_at"]
        cur.execute(
            """
            UPDATE operations.entity_observation_history
               SET effective_to = %(effective_to)s,
                   last_seen_at = %(last_seen_at)s
             WHERE tenant_id = %(tenant_id)s
               AND source_binding_id = %(source_binding_id)s
               AND entity_type = %(entity_type)s
               AND parent_source_key = %(parent_source_key)s
               AND entity_key = %(entity_key)s
               AND effective_to IS NULL
            """,
            {
                "tenant_id": identity[0], "source_binding_id": identity[1],
                "entity_type": identity[2], "parent_source_key": identity[3],
                "entity_key": identity[4], "effective_to": row["observed_at"],
                "last_seen_at": prior_last_seen,
            },
        )
    history_rows = [{
        "id": row["observation_id"],
        "tenant_id": row["tenant_id"],
        "source_binding_id": row["source_binding_id"],
        "collector_instance_id": row["collector_instance_id"],
        "client_id": row.get("client_id"),
        "device_id": row.get("device_id"),
        "entity_type": row["entity_type"],
        "platform": row.get("platform", ""),
        "parent_source_key": row.get("parent_source_key") or "",
        "entity_key": row["entity_key"],
        "effective_from": row["observed_at"],
        "effective_to": None,
        # New state's last_seen_at IS the new observation time — this is a
        # different concept than the close's last_seen_at above.
        "last_seen_at": row.get("last_seen_at") or row["observed_at"],
        "received_at": row.get("last_received_at") or row["observed_at"],
        "material_data": row["material_data"],
        "material_hash": row["material_hash"],
        "hash_algorithm_version": row["hash_algorithm_version"],
        "active": row.get("active", True),
    } for row in prepared]
    # Bespoke insert with ON CONFLICT DO NOTHING on the identity partial
    # unique index. Keeps history append-only.
    cols = list(history_rows[0].keys())
    cols_sql = ", ".join(cols)
    placeholders_sql = ", ".join(f"%({c})s" for c in cols)
    stmt = (
        f"INSERT INTO operations.entity_observation_history ({cols_sql}) "
        f"VALUES ({placeholders_sql}) "
        "ON CONFLICT (id) DO NOTHING"
    )
    cur.executemany(stmt, history_rows)
    return cur.rowcount
