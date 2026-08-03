"""Shared observation normalization and current/history write primitive.

Connector-specific code supplies already-normalized row dictionaries.  Keeping
material hashing here ensures all writers use the same policy and hash version.

Correctness contract (per ADR-0007 §Heartbeat/§SCD-2 and ADR-0009):

- Existing identities serialize on their current-row lock. Brand-new
  identities take a per-tuple advisory lock and then re-read because
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
- Locking, lookup, conflict handling, and history use ADR-0009's stable source
  identity. Transport binding and Operations classification remain mutable
  provenance/state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Json

MATERIAL_HASH_VERSION = 1
LEGACY_MATERIAL_PROJECTION_VERSION = 1
VOLATILE_FIELDS = frozenset(
    {
        "last_seen_at",
        "last_contact",
        "is_online",
        "offline",
        "hostStateChangeDate",
        "lastActive",
        "last_boot_time_at",
        "power_state",
    }
)

# ADR-0010 record contracts. Hashing remains shared; the selected normalized
# fields vary by stable record namespace. Existing non-Ninja records retain the
# deployed fallback during this additive release.
_NINJA_DEVICE_MATERIAL_FIELDS = frozenset(
    {
        "hostname",
        "platform",
        "entity_type",
        "node_class",
        "vm_uuid",
        "is_vm",
        "serial_number",
        "macs",
        "device_role",
        "os_name",
        "os_family",
        "domain",
        "offline",
        "needs_reboot",
        "needs_reboot_reasons",
        "last_boot_time_at",
        "hypervisor_reported_boot_time_at",
        "maintenance_status",
        "maintenance_start_at",
        "maintenance_end_at",
        "power_state",
        "parent_ninja_id",
    }
)
_NINJA_HEALTH_MATERIAL_FIELDS = frozenset(
    {
        "platform",
        "entity_type",
        "pending_reboot_reason",
        "failed_os_patches_count",
        "pending_os_patches_count",
        "failed_software_patches_count",
        "pending_software_patches_count",
        "alert_count",
        "active_job_count",
        "health_status",
        "active_threats_count",
        "quarantined_threats_count",
        "blocked_threats_count",
        "critical_vulnerability_count",
        "high_vulnerability_count",
        "medium_vulnerability_count",
        "low_vulnerability_count",
        "installation_issues_count",
        "offline",
        "parent_offline",
        "products_installation_statuses",
    }
)

# Columns written to entity_observation_current. Kept as a module constant so
# the bespoke upsert SQL and the row-shaping loop stay in lockstep.
_CURRENT_COLUMNS: tuple[str, ...] = (
    "observation_id",
    "tenant_id",
    "source_binding_id",
    "source_instance_id",
    "last_seen_binding_id",
    "external_namespace",
    "parent_external_namespace",
    "parent_external_id",
    "external_id",
    "collector_instance_id",
    "client_id",
    "device_id",
    "entity_type",
    "parent_source_key",
    "entity_key",
    "platform",
    "subplatform",
    "observed_at",
    "last_seen_at",
    "last_received_at",
    "active",
    "withdrawn_at",
    "snapshot_scope",
    "last_snapshot_run_id",
    "raw_data",
    "canonical_data",
    "raw_hash",
    "material_hash",
    "hash_algorithm_version",
    "material_projection_version",
    "batch_id",
    "collector_version",
    "schema_version",
)

# Columns updated with EXCLUDED.c on conflict. Stable identity columns are
# carried by ON CONFLICT. client_id/device_id use COALESCE to preserve post-hoc
# resolver writes against fresh connector NULLs. observation_id remains stable
# across heartbeats because identity_candidates depends on it.
_CURRENT_UPDATE_COLUMNS: tuple[str, ...] = (
    "source_binding_id",
    "last_seen_binding_id",
    "collector_instance_id",
    "entity_type",
    "parent_source_key",
    "entity_key",
    "platform",
    "subplatform",
    "observed_at",
    "last_seen_at",
    "last_received_at",
    "active",
    "withdrawn_at",
    "snapshot_scope",
    "last_snapshot_run_id",
    "raw_data",
    "canonical_data",
    "raw_hash",
    "material_hash",
    "hash_algorithm_version",
    "material_projection_version",
    "batch_id",
    "collector_version",
    "schema_version",
)


def _json_object(value: Any) -> dict[str, Any]:
    if hasattr(value, "obj"):
        value = value.obj
    return value if isinstance(value, dict) else {}


def raw_hash(raw: Any) -> bytes:
    """Hash a deterministic representation of the complete parsed payload."""
    payload = json.dumps(
        _json_object(raw),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


def material_projection(
    canonical: dict[str, Any],
    *,
    platform: str = "",
    external_namespace: str = "",
    entity_type: str = "",
    use_versioned_contracts: bool = True,
) -> dict[str, Any]:
    del entity_type  # Reserved for future entity-family refinements.
    canonical = _json_object(canonical)
    fields: frozenset[str] | None = None
    if use_versioned_contracts and platform.casefold() == "ninja":
        if external_namespace == "device":
            fields = _NINJA_DEVICE_MATERIAL_FIELDS
        elif external_namespace == "device-health":
            fields = _NINJA_HEALTH_MATERIAL_FIELDS
    if fields is None:
        return {
            key: canonical[key]
            for key in sorted(canonical)
            if key not in VOLATILE_FIELDS
        }
    return {key: canonical[key] for key in sorted(fields) if key in canonical}


def material_projection_version(
    *,
    platform: str,
    external_namespace: str,
    use_versioned_contracts: bool = True,
) -> int:
    if not use_versioned_contracts or platform.casefold() != "ninja":
        return LEGACY_MATERIAL_PROJECTION_VERSION
    if external_namespace == "device":
        return 3
    return LEGACY_MATERIAL_PROJECTION_VERSION


def material_hash(
    canonical: dict[str, Any],
    *,
    platform: str = "",
    external_namespace: str = "",
    entity_type: str = "",
    use_versioned_contracts: bool = True,
) -> bytes:
    payload = json.dumps(
        material_projection(
            canonical,
            platform=platform,
            external_namespace=external_namespace,
            entity_type=entity_type,
            use_versioned_contracts=use_versioned_contracts,
        ),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


def prepare_observation(
    row: dict[str, Any],
    *,
    use_versioned_contracts: bool = True,
) -> dict[str, Any]:
    row = dict(row)
    if row.get("source_instance_id") is None:
        raise ValueError("source_instance_id is required for observation dual-write")
    if row.get("source_binding_id") is None:
        raise ValueError("source_binding_id is required for observation provenance")

    external_namespace = str(row.get("external_namespace") or "").strip()
    external_id = str(row.get("external_id") or "").strip()
    parent_namespace = str(row.get("parent_external_namespace") or "").strip()
    parent_id = str(row.get("parent_external_id") or "").strip()
    if not external_namespace:
        raise ValueError("external_namespace is required for observation dual-write")
    if not external_id:
        raise ValueError("external_id is required for observation dual-write")
    if bool(parent_namespace) != bool(parent_id):
        raise ValueError(
            "parent_external_namespace and parent_external_id must both be empty "
            "or both be populated"
        )
    row["external_namespace"] = external_namespace
    row["external_id"] = external_id
    row["parent_external_namespace"] = parent_namespace
    row["parent_external_id"] = parent_id
    row["last_seen_binding_id"] = (
        row.get("last_seen_binding_id") or row["source_binding_id"]
    )

    canonical = _json_object(row.get("canonical_data"))
    raw_data = _json_object(row.get("raw_data"))
    row["raw_data"] = Json(raw_data)
    row["canonical_data"] = Json(canonical)
    row["raw_hash"] = raw_hash(raw_data)
    projection_kwargs = {
        "platform": str(row.get("platform") or ""),
        "external_namespace": external_namespace,
        "entity_type": str(row.get("entity_type") or ""),
        "use_versioned_contracts": use_versioned_contracts,
    }
    row["material_hash"] = material_hash(canonical, **projection_kwargs)
    row["material_data"] = Json(material_projection(canonical, **projection_kwargs))
    row["hash_algorithm_version"] = MATERIAL_HASH_VERSION
    row["material_projection_version"] = material_projection_version(
        platform=projection_kwargs["platform"],
        external_namespace=external_namespace,
        use_versioned_contracts=use_versioned_contracts,
    )
    return row


def prepare_batch(
    rows: Iterable[dict[str, Any]],
    *,
    use_versioned_contracts: bool = True,
) -> list[dict[str, Any]]:
    return [
        prepare_observation(row, use_versioned_contracts=use_versioned_contracts)
        for row in rows
    ]


def _supports_projection_versions(cur: Any) -> bool:
    """Tolerate the short Operations-migration/ingest restart race."""
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM pg_attribute
             WHERE attrelid = 'operations.entity_observation_current'::regclass
               AND attname = 'material_projection_version'
               AND NOT attisdropped
        )
        """
    )
    result = cur.fetchone()
    return bool(result and result[0])


def write_daily_presence_rows(
    cur: Any,
    rows: Iterable[dict[str, Any]],
    *,
    snapshot_run_id: Any,
    observed_at: datetime,
) -> int:
    """Insert one compact source-record presence fact per UTC day.

    The current row owns the complete stable identity. The rollup references
    its stable observation UUID and duplicates only namespace/date provenance.
    Repeated collections on the same day conflict to no-op.
    """
    identities = [
        {
            "tenant_id": row["tenant_id"],
            "source_instance_id": str(row["source_instance_id"]),
            "external_namespace": str(row["external_namespace"]),
            "parent_external_namespace": str(
                row.get("parent_external_namespace") or ""
            ),
            "parent_external_id": str(row.get("parent_external_id") or ""),
            "external_id": str(row["external_id"]),
        }
        for row in rows
    ]
    if not identities:
        return 0
    cur.execute("SELECT to_regclass('operations.source_record_seen_daily')")
    if cur.fetchone()[0] is None:
        return 0
    rollup_day = observed_at.astimezone(timezone.utc).date()
    cur.execute(
        """
        WITH incoming AS (
            SELECT *
              FROM jsonb_to_recordset(%s::jsonb) AS x(
                   tenant_id bigint,
                   source_instance_id uuid,
                   external_namespace text,
                   parent_external_namespace text,
                   parent_external_id text,
                   external_id text
              )
        )
        INSERT INTO operations.source_record_seen_daily
          (tenant_id, source_record_id, external_namespace, rollup_day,
           first_snapshot_run_id)
        SELECT c.tenant_id, c.observation_id, c.external_namespace, %s, %s
          FROM incoming i
          JOIN operations.entity_observation_current c
            ON c.tenant_id = i.tenant_id
           AND c.source_instance_id = i.source_instance_id
           AND c.external_namespace = i.external_namespace
           AND c.parent_external_namespace = i.parent_external_namespace
           AND c.parent_external_id = i.parent_external_id
           AND c.external_id = i.external_id
         WHERE c.active IS TRUE
        ON CONFLICT (tenant_id, source_record_id, rollup_day) DO NOTHING
        """,
        (Json(identities), rollup_day, snapshot_run_id),
    )
    return cur.rowcount


def _identity_tuple(row: dict[str, Any]) -> tuple:
    """ADR-0009 stable source identity used for sort and locking."""
    return (
        row["tenant_id"],
        str(row["source_instance_id"]),
        row["external_namespace"],
        row["parent_external_namespace"],
        row["parent_external_id"],
        row["external_id"],
    )


def _identity_lock_key(row: dict[str, Any]) -> str:
    """Deterministic string fed to pg_advisory_xact_lock via hashtextextended.

    Two batches that share missing identity tuples must acquire their advisory
    locks in the same order. The caller sorts by _identity_tuple before
    iterating; existing tuples serialize on their current-row locks instead.
    """
    return "|".join(str(part) for part in _identity_tuple(row))


def _select_current_for_update(
    cur: Any,
    row: dict[str, Any],
    *,
    include_projection_version: bool,
) -> tuple | None:
    projection_column = (
        ", material_projection_version" if include_projection_version else ""
    )
    cur.execute(
        f"""
        SELECT observed_at, material_hash, active, client_id, device_id,
               last_seen_at{projection_column}
          FROM operations.entity_observation_current
         WHERE tenant_id = %s AND source_instance_id = %s
           AND external_namespace = %s
           AND parent_external_namespace = %s
           AND parent_external_id = %s
           AND external_id = %s
         FOR UPDATE
        """,
        _identity_tuple(row),
    )
    return cur.fetchone()


def write_current_rows(cur: Any, rows: Iterable[dict[str, Any]]) -> int:
    """Upsert prepared rows into the current-state table.

    Per ADR-0007 hardening, each existing row is processed under its row lock.
    A missing identity additionally takes a transaction-scoped advisory lock
    keyed on the identity tuple and re-reads, so absent-row races between
    concurrent writers are serialized without retaining one advisory lock for
    every heartbeat in a large snapshot. For each locked identity:

    1. Read prior state under `SELECT ... FOR UPDATE`. If absent, take the
       identity advisory lock and re-read under the lock.
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
    use_versioned_contracts = _supports_projection_versions(cur)
    prepared = prepare_batch(
        rows,
        use_versioned_contracts=use_versioned_contracts,
    )
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

        # (1) Existing rows serialize on their row lock. Only an absent tuple
        # needs an advisory lock; re-read after acquiring it because another
        # writer may have inserted while this transaction was waiting.
        prev = _select_current_for_update(
            cur,
            row,
            include_projection_version=use_versioned_contracts,
        )
        if prev is None:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (_identity_lock_key(row),),
            )
            prev = _select_current_for_update(
                cur,
                row,
                include_projection_version=use_versioned_contracts,
            )

        # (2) Out-of-order / equal-timestamp guard runs BEFORE any history
        # mutation so an older or duplicate snapshot cannot open a phantom
        # SCD-2 interval.
        if prev is not None and prev[0] is not None and row["observed_at"] <= prev[0]:
            continue

        # (3) Material, material-contract, or presence transition detection.
        # A projection-version boundary must also close and reopen history;
        # otherwise current could advertise the new contract while its open
        # SCD-2 version still advertises the old one when the hash is equal.
        is_new = prev is None
        material_changed = not is_new and (
            prev[1] != row["material_hash"]
            or prev[2] != row.get("active", True)
            or (
                use_versioned_contracts
                and prev[6] != row["material_projection_version"]
            )
        )
        if is_new or material_changed:
            # Side-band the prior last_seen_at so write_history_changes can
            # close the open version at its true last-confirmed time (not
            # the new observation's time).
            row["_prior_last_seen_at"] = None if is_new else prev[5]
            changed_for_history.append(row)

        # (4) Resolved-ID preservation — mirrored in the SQL COALESCE below
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
        write_history_changes(
            cur,
            changed_for_history,
            use_versioned_contracts=use_versioned_contracts,
        )

    if not to_upsert:
        return 0

    return _upsert_current(
        cur,
        to_upsert,
        include_projection_version=use_versioned_contracts,
    )


def _upsert_current(
    cur: Any,
    rows: list[dict[str, Any]],
    *,
    include_projection_version: bool,
) -> int:
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

    current_columns = tuple(
        column
        for column in _CURRENT_COLUMNS
        if include_projection_version or column != "material_projection_version"
    )
    update_columns = tuple(
        column
        for column in _CURRENT_UPDATE_COLUMNS
        if include_projection_version or column != "material_projection_version"
    )
    shaped = [{key: row.get(key) for key in current_columns} for row in rows]
    cols_sql = ", ".join(current_columns)
    placeholders_sql = ", ".join(f"%({c})s" for c in current_columns)

    update_pieces = [
        "client_id = COALESCE(EXCLUDED.client_id, "
        "operations.entity_observation_current.client_id)",
        "device_id = COALESCE(EXCLUDED.device_id, "
        "operations.entity_observation_current.device_id)",
    ]
    for c in update_columns:
        update_pieces.append(f"{c} = EXCLUDED.{c}")
    update_sql = ", ".join(update_pieces)

    stmt = (
        f"INSERT INTO operations.entity_observation_current ({cols_sql}) "
        f"VALUES ({placeholders_sql}) "
        "ON CONFLICT (tenant_id, source_instance_id, external_namespace, "
        "parent_external_namespace, parent_external_id, external_id) "
        "DO UPDATE SET "
        f"{update_sql} "
        "WHERE operations.entity_observation_current.observed_at "
        "< EXCLUDED.observed_at"
    )
    cur.executemany(stmt, shaped)
    return cur.rowcount


def write_history_changes(
    cur: Any,
    rows: Iterable[dict[str, Any]],
    *,
    use_versioned_contracts: bool | None = None,
) -> int:
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
    if use_versioned_contracts is None:
        use_versioned_contracts = _supports_projection_versions(cur)
    prepared = prepare_batch(
        rows,
        use_versioned_contracts=use_versioned_contracts,
    )
    if not prepared:
        return 0
    for row in prepared:
        prior_last_seen = row.get("_prior_last_seen_at") or row["observed_at"]
        cur.execute(
            """
            UPDATE operations.entity_observation_history
               SET effective_to = %(effective_to)s,
                   last_seen_at = %(last_seen_at)s,
                   closed_by_snapshot_run_id = %(closed_by_snapshot_run_id)s
             WHERE tenant_id = %(tenant_id)s
               AND source_instance_id = %(source_instance_id)s
               AND external_namespace = %(external_namespace)s
               AND parent_external_namespace = %(parent_external_namespace)s
               AND parent_external_id = %(parent_external_id)s
               AND external_id = %(external_id)s
               AND effective_to IS NULL
            """,
            {
                "tenant_id": row["tenant_id"],
                "source_instance_id": row["source_instance_id"],
                "external_namespace": row["external_namespace"],
                "parent_external_namespace": row["parent_external_namespace"],
                "parent_external_id": row["parent_external_id"],
                "external_id": row["external_id"],
                "effective_to": row["observed_at"],
                "last_seen_at": prior_last_seen,
                "closed_by_snapshot_run_id": row.get("last_snapshot_run_id"),
            },
        )
    history_rows = [
        {
            "id": row["observation_id"],
            "tenant_id": row["tenant_id"],
            "source_binding_id": row["source_binding_id"],
            "source_instance_id": row["source_instance_id"],
            "last_seen_binding_id": row["last_seen_binding_id"],
            "external_namespace": row["external_namespace"],
            "parent_external_namespace": row["parent_external_namespace"],
            "parent_external_id": row["parent_external_id"],
            "external_id": row["external_id"],
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
            "material_projection_version": row["material_projection_version"],
            "active": row.get("active", True),
            "closed_by_snapshot_run_id": None,
        }
        for row in prepared
    ]
    # Bespoke insert with ON CONFLICT DO NOTHING on the identity partial
    # unique index. Keeps history append-only.
    cols = list(history_rows[0].keys())
    if not use_versioned_contracts:
        cols.remove("material_projection_version")
    cols_sql = ", ".join(cols)
    placeholders_sql = ", ".join(f"%({c})s" for c in cols)
    stmt = (
        f"INSERT INTO operations.entity_observation_history ({cols_sql}) "
        f"VALUES ({placeholders_sql}) "
        "ON CONFLICT (id) DO NOTHING"
    )
    cur.executemany(stmt, history_rows)
    return cur.rowcount
