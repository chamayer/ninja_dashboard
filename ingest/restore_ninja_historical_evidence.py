"""Restore stable generic evidence for withdrawn legacy Ninja devices.

This operator tool exists only to make retained legacy daily snapshots
referencable by the generic daily rollup. It defaults to a read-only
measurement, emits aggregate results, and never creates canonical entities or
source links. Apply mode restores one inactive current source record and one
closed history interval per eligible stable Ninja identity.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ingest import db
from ingest.normalize import (
    entity_type_for_node_class,
    infer_device_role,
    normalize_mac,
    os_family,
)
from ingest.observations import prepare_observation
from ingest.util import ninja_epoch_to_dt

_RESTORATION_NAMESPACE = uuid.UUID("9d82ec99-8e54-4b15-990a-e2c53cb52f59")
_COLLECTOR_VERSION = "ninja-historical-evidence-restoration-v1"
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
NINJA_DEVICE_EXTERNAL_NAMESPACE = "device"


class RestorationBlocked(RuntimeError):
    """Raised without source identifiers when restoration cannot proceed."""


@dataclass(frozen=True)
class RestorationResult:
    start_day: date
    end_day: date
    legacy_identities: int
    existing_generic_identities: int
    missing_generic_identities: int
    eligible_identities: int
    blocked_identities: int
    current_legacy_blockers: int
    withdrawal_boundary_blockers: int
    raw_evidence_blockers: int
    canonical_link_blockers: int
    history_evidence_blockers: int
    interval_blockers: int
    inserted_current_rows: int
    inserted_history_rows: int
    apply: bool

    @property
    def blocker_count(self) -> int:
        return self.blocked_identities


def _utc_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    start = datetime(
        start_day.year, start_day.month, start_day.day, tzinfo=timezone.utc
    )
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc)
    return start, end + timedelta(days=1)


def _source_provenance(cur: Any, *, tenant_id: int) -> tuple[uuid.UUID, uuid.UUID]:
    cur.execute(
        """
        SELECT sb.source_instance_id, sb.collector_instance_id
          FROM operations.source_bindings sb
          JOIN operations.source_instances si
            ON si.id = sb.source_instance_id
           AND si.tenant_id = sb.tenant_id
          JOIN operations.sources s ON s.id = si.source_id
         WHERE sb.id = %s
           AND sb.tenant_id = %s
           AND lower(s.name) = 'ninja'
        """,
        (NINJA_SOURCE_BINDING_ID, tenant_id),
    )
    rows = cur.fetchall()
    if len(rows) != 1:
        raise RestorationBlocked("Ninja source provenance is not uniquely configured")
    source_instance_id, collector_instance_id = rows[0]
    if collector_instance_id != INTERNAL_COLLECTOR_INSTANCE_ID:
        raise RestorationBlocked(
            "Ninja collector provenance does not match the contract"
        )
    return source_instance_id, collector_instance_id


def measure_range(
    cur: Any,
    *,
    tenant_id: int,
    start_day: date,
    end_day: date,
) -> RestorationResult:
    """Measure missing identities and every fail-closed eligibility condition."""
    start_at, end_at = _utc_bounds(start_day, end_day)
    source_instance_id, _collector_instance_id = _source_provenance(
        cur,
        tenant_id=tenant_id,
    )
    cur.execute(
        """
        WITH targets AS (
            SELECT s.device_id,
                   MIN(all_s.snapshot_at) AS first_snapshot_at,
                   MAX(all_s.snapshot_at) AS last_snapshot_at
              FROM (
                    SELECT DISTINCT device_id
                      FROM ninja_core.device_snapshots
                     WHERE snapshot_at >= %s
                       AND snapshot_at < %s
                   ) s
              JOIN ninja_core.device_snapshots all_s
                ON all_s.device_id = s.device_id
             GROUP BY s.device_id
        ), assessed AS (
            SELECT t.device_id,
                   (c.observation_id IS NOT NULL) AS has_generic,
                   d.is_current IS TRUE AS is_current,
                   d.missing_since IS NULL AS lacks_withdrawal,
                   d.data IS NULL
                       OR jsonb_typeof(d.data) IS DISTINCT FROM 'object'
                       OR d.data = '{}'::jsonb AS lacks_raw,
                   EXISTS (
                       SELECT 1
                         FROM operations.device_links dl
                         JOIN operations.sources ls ON ls.id = dl.source_id
                        WHERE dl.tenant_id = %s
                          AND lower(ls.name) = 'ninja'
                          AND dl.external_id = d.id::text
                   ) AS has_canonical_link,
                   EXISTS (
                       SELECT 1
                         FROM operations.entity_observation_history h
                        WHERE h.tenant_id = %s
                          AND h.source_instance_id = %s
                          AND h.external_namespace = 'device'
                          AND h.parent_external_namespace = ''
                          AND h.parent_external_id = ''
                          AND h.external_id = d.id::text
                   ) AS has_generic_history,
                   d.missing_since IS NOT NULL AND (
                       LEAST(d.first_seen_at, t.first_snapshot_at)
                           >= d.missing_since
                       OR GREATEST(d.last_seen_at, t.last_snapshot_at)
                           >= d.missing_since
                   ) AS invalid_interval
              FROM targets t
              JOIN ninja_core.devices d ON d.id = t.device_id
              LEFT JOIN operations.entity_observation_current c
                ON c.tenant_id = %s
               AND c.source_instance_id = %s
               AND c.external_namespace = 'device'
               AND c.parent_external_namespace = ''
               AND c.parent_external_id = ''
               AND c.external_id = d.id::text
        )
        SELECT COUNT(*)::bigint,
               COUNT(*) FILTER (WHERE has_generic)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic)::bigint,
               COUNT(*) FILTER (
                   WHERE NOT has_generic AND NOT is_current
                     AND NOT lacks_withdrawal AND NOT lacks_raw
                     AND NOT has_canonical_link AND NOT has_generic_history
                     AND NOT invalid_interval
               )::bigint,
               COUNT(*) FILTER (
                   WHERE NOT has_generic AND (
                       is_current OR lacks_withdrawal OR lacks_raw
                       OR has_canonical_link OR has_generic_history
                       OR invalid_interval
                   )
               )::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND is_current)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND lacks_withdrawal)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND lacks_raw)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND has_canonical_link)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND has_generic_history)::bigint,
               COUNT(*) FILTER (WHERE NOT has_generic AND invalid_interval)::bigint
          FROM assessed
        """,
        (
            start_at,
            end_at,
            tenant_id,
            tenant_id,
            source_instance_id,
            tenant_id,
            source_instance_id,
        ),
    )
    values = cur.fetchone()
    return RestorationResult(
        start_day=start_day,
        end_day=end_day,
        legacy_identities=values[0],
        existing_generic_identities=values[1],
        missing_generic_identities=values[2],
        eligible_identities=values[3],
        blocked_identities=values[4],
        current_legacy_blockers=values[5],
        withdrawal_boundary_blockers=values[6],
        raw_evidence_blockers=values[7],
        canonical_link_blockers=values[8],
        history_evidence_blockers=values[9],
        interval_blockers=values[10],
        inserted_current_rows=0,
        inserted_history_rows=0,
        apply=False,
    )


def _eligible_rows(
    cur: Any,
    *,
    tenant_id: int,
    start_day: date,
    end_day: date,
) -> list[dict[str, Any]]:
    start_at, end_at = _utc_bounds(start_day, end_day)
    source_instance_id, collector_instance_id = _source_provenance(
        cur,
        tenant_id=tenant_id,
    )
    cur.execute(
        """
        WITH target_ids AS (
            SELECT DISTINCT device_id
              FROM ninja_core.device_snapshots
             WHERE snapshot_at >= %s
               AND snapshot_at < %s
        ), snapshot_stats AS (
            SELECT s.device_id,
                   MIN(s.snapshot_at) AS first_snapshot_at,
                   MAX(s.snapshot_at) AS last_snapshot_at
              FROM ninja_core.device_snapshots s
              JOIN target_ids t ON t.device_id = s.device_id
             GROUP BY s.device_id
        ), latest_snapshot AS (
            SELECT DISTINCT ON (s.device_id)
                   s.device_id, s.snapshot_at, s.offline, s.last_contact,
                   s.last_boot, s.needs_reboot, s.needs_reboot_reasons,
                   s.last_user, s.maintenance_status, s.maintenance_start,
                   s.maintenance_end
              FROM ninja_core.device_snapshots s
              JOIN target_ids t ON t.device_id = s.device_id
             ORDER BY s.device_id, s.snapshot_at DESC
        )
        SELECT d.id, d.uid, d.node_class, d.display_name, d.system_name,
               d.dns_name, d.os_name, d.serial_number,
               d.is_virtual_machine, d.mac_addresses, d.data,
               LEAST(d.first_seen_at, ss.first_snapshot_at) AS effective_from,
               GREATEST(d.last_seen_at, ss.last_snapshot_at) AS last_observed_at,
               d.missing_since, ls.offline, ls.last_contact, ls.last_boot,
               ls.needs_reboot, ls.needs_reboot_reasons, ls.last_user,
               ls.maintenance_status, ls.maintenance_start,
               ls.maintenance_end
          FROM target_ids t
          JOIN ninja_core.devices d ON d.id = t.device_id
          JOIN snapshot_stats ss ON ss.device_id = d.id
          JOIN latest_snapshot ls ON ls.device_id = d.id
          LEFT JOIN operations.entity_observation_current c
            ON c.tenant_id = %s
           AND c.source_instance_id = %s
           AND c.external_namespace = 'device'
           AND c.parent_external_namespace = ''
           AND c.parent_external_id = ''
           AND c.external_id = d.id::text
         WHERE c.observation_id IS NULL
           AND d.is_current IS FALSE
           AND d.missing_since IS NOT NULL
           AND jsonb_typeof(d.data) = 'object'
           AND d.data <> '{}'::jsonb
           AND LEAST(d.first_seen_at, ss.first_snapshot_at) < d.missing_since
           AND GREATEST(d.last_seen_at, ss.last_snapshot_at) < d.missing_since
           AND NOT EXISTS (
               SELECT 1
                 FROM operations.device_links dl
                 JOIN operations.sources s ON s.id = dl.source_id
                WHERE dl.tenant_id = %s
                  AND lower(s.name) = 'ninja'
                  AND dl.external_id = d.id::text
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM operations.entity_observation_history h
                WHERE h.tenant_id = %s
                  AND h.source_instance_id = %s
                  AND h.external_namespace = 'device'
                  AND h.parent_external_namespace = ''
                  AND h.parent_external_id = ''
                  AND h.external_id = d.id::text
           )
         ORDER BY d.id
        """,
        (
            start_at,
            end_at,
            tenant_id,
            source_instance_id,
            tenant_id,
            tenant_id,
            source_instance_id,
        ),
    )
    columns = [column.name for column in cur.description]
    rows = [dict(zip(columns, values, strict=True)) for values in cur.fetchall()]
    for row in rows:
        row["source_instance_id"] = source_instance_id
        row["collector_instance_id"] = collector_instance_id
    return rows


def _canonical_data(row: dict[str, Any]) -> dict[str, Any]:
    raw = row["data"] if isinstance(row["data"], dict) else {}
    node_class = row["node_class"]
    entity_type = entity_type_for_node_class(node_class)
    offline = row["offline"]
    last_boot = row["last_boot"]
    node_upper = (node_class or "").upper()
    is_vm_record = node_upper.endswith(
        ("_VMM_GUEST", "_VM_GUEST", "_VMM_HOST", "_VM_HOST")
    )
    if is_vm_record:
        vm_last_boot = ninja_epoch_to_dt(raw.get("lastBootTime"))
        if vm_last_boot is not None:
            last_boot = vm_last_boot
    canonical = {
        "hostname": row["system_name"] or row["display_name"] or row["dns_name"],
        "platform": "Ninja",
        "entity_type": entity_type,
        "node_class": node_class,
        "vm_uuid": str(row["uid"]) if row["uid"] else None,
        "is_vm": row["is_virtual_machine"],
        "last_seen_at": (
            row["last_contact"].isoformat() if row["last_contact"] else None
        ),
        "last_contact_at": (
            row["last_contact"].isoformat() if row["last_contact"] else None
        ),
        "is_online": None if offline is None else not offline,
        "offline": offline,
        "last_boot_time_at": last_boot.isoformat() if last_boot else None,
        "needs_reboot": row["needs_reboot"],
        "needs_reboot_reasons": row["needs_reboot_reasons"],
        "last_user": row["last_user"],
        "maintenance_status": row["maintenance_status"],
        "maintenance_start_at": (
            row["maintenance_start"].isoformat() if row["maintenance_start"] else None
        ),
        "maintenance_end_at": (
            row["maintenance_end"].isoformat() if row["maintenance_end"] else None
        ),
        "serial_number": row["serial_number"],
        "macs": sorted(
            {
                normalized
                for value in (row["mac_addresses"] or [])
                if isinstance(value, str)
                and (normalized := normalize_mac(value)) is not None
            }
        ),
        "device_role": infer_device_role(row["os_name"], node_class),
        "os_name": row["os_name"],
        "os_family": os_family(row["os_name"]),
        "domain": (
            row["dns_name"].split(".", 1)[1]
            if row["dns_name"] and "." in row["dns_name"]
            else None
        ),
    }
    if is_vm_record:
        power_state = raw.get("powerState")
        canonical["power_state"] = (
            power_state.lower() if isinstance(power_state, str) else None
        )
        canonical["parent_ninja_id"] = raw.get("parentDeviceId")
    return canonical


def _prepared_row(row: dict[str, Any], *, tenant_id: int) -> dict[str, Any]:
    external_id = str(row["id"])
    observation_id = uuid.uuid5(
        _RESTORATION_NAMESPACE,
        f"{tenant_id}:{row['source_instance_id']}:device:{external_id}",
    )
    entity_type = entity_type_for_node_class(row["node_class"])
    source_row = {
        "observation_id": observation_id,
        "tenant_id": tenant_id,
        "source_binding_id": NINJA_SOURCE_BINDING_ID,
        "source_instance_id": row["source_instance_id"],
        "last_seen_binding_id": NINJA_SOURCE_BINDING_ID,
        "external_namespace": NINJA_DEVICE_EXTERNAL_NAMESPACE,
        "parent_external_namespace": "",
        "parent_external_id": "",
        "external_id": external_id,
        "collector_instance_id": row["collector_instance_id"],
        "client_id": None,
        "device_id": None,
        "entity_type": entity_type,
        "parent_source_key": "",
        "entity_key": external_id,
        "platform": "Ninja",
        "subplatform": "",
        "observed_at": row["last_observed_at"],
        "last_seen_at": row["last_observed_at"],
        "last_received_at": row["last_observed_at"],
        "active": False,
        "withdrawn_at": row["missing_since"],
        "snapshot_scope": "Ninja",
        "last_snapshot_run_id": None,
        "raw_data": row["data"],
        "canonical_data": _canonical_data(row),
        "batch_id": uuid.uuid5(_RESTORATION_NAMESPACE, f"batch:{observation_id}"),
        "collector_version": _COLLECTOR_VERSION,
        "schema_version": 1,
    }
    prepared = prepare_observation(source_row, use_versioned_contracts=True)
    prepared["effective_from"] = row["effective_from"]
    prepared["effective_to"] = row["missing_since"]
    return prepared


_CURRENT_COLUMNS = (
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


def _insert_prepared(cur: Any, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    current_columns = ", ".join(_CURRENT_COLUMNS)
    current_values = ", ".join(f"%({column})s" for column in _CURRENT_COLUMNS)
    cur.executemany(
        f"INSERT INTO operations.entity_observation_current "
        f"({current_columns}) VALUES ({current_values})",
        rows,
    )
    current_count = cur.rowcount

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
            "client_id": None,
            "device_id": None,
            "entity_type": row["entity_type"],
            "platform": row["platform"],
            "parent_source_key": "",
            "entity_key": row["entity_key"],
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
            "last_seen_at": row["last_seen_at"],
            "received_at": row["last_received_at"],
            "material_data": row["material_data"],
            "material_hash": row["material_hash"],
            "hash_algorithm_version": row["hash_algorithm_version"],
            "material_projection_version": row["material_projection_version"],
            "active": True,
            "closed_by_snapshot_run_id": None,
        }
        for row in rows
    ]
    history_columns = tuple(history_rows[0])
    columns_sql = ", ".join(history_columns)
    values_sql = ", ".join(f"%({column})s" for column in history_columns)
    cur.executemany(
        f"INSERT INTO operations.entity_observation_history "
        f"({columns_sql}) VALUES ({values_sql})",
        history_rows,
    )
    return current_count, cur.rowcount


def process_range(
    cur: Any,
    *,
    tenant_id: int,
    start_day: date,
    end_day: date,
    apply: bool,
) -> RestorationResult:
    measured = measure_range(
        cur,
        tenant_id=tenant_id,
        start_day=start_day,
        end_day=end_day,
    )
    if not apply:
        return measured
    if (
        measured.blocker_count
        or measured.eligible_identities != measured.missing_generic_identities
    ):
        raise RestorationBlocked(
            "historical evidence restoration has fail-closed eligibility blockers"
        )
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"ninja-historical-evidence:{tenant_id}",),
    )
    # Re-measure under the operation lock so a concurrent writer cannot turn a
    # preflight result into a partial restoration.
    measured = measure_range(
        cur,
        tenant_id=tenant_id,
        start_day=start_day,
        end_day=end_day,
    )
    if (
        measured.blocker_count
        or measured.eligible_identities != measured.missing_generic_identities
    ):
        raise RestorationBlocked(
            "historical evidence restoration changed during locked preflight"
        )
    rows = [
        _prepared_row(row, tenant_id=tenant_id)
        for row in _eligible_rows(
            cur,
            tenant_id=tenant_id,
            start_day=start_day,
            end_day=end_day,
        )
    ]
    if len(rows) != measured.eligible_identities:
        raise RestorationBlocked("historical evidence restoration selection changed")
    current_count, history_count = _insert_prepared(cur, rows)
    if current_count != len(rows) or history_count != len(rows):
        raise RestorationBlocked(
            "historical evidence restoration insert was incomplete"
        )
    return RestorationResult(
        **{
            **asdict(measured),
            "inserted_current_rows": current_count,
            "inserted_history_rows": history_count,
            "apply": True,
        }
    )


def run(
    *,
    start_day: date,
    end_day: date,
    tenant_id: int = 1,
    apply: bool = False,
) -> RestorationResult:
    if start_day > end_day:
        raise ValueError("start_day must be on or before end_day")
    if end_day >= datetime.now(timezone.utc).date():
        raise ValueError("end_day must be a completed UTC day")
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")
    with db.transaction() as cur:
        if apply:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        else:
            cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            "SELECT set_config('operations.tenant_id', %s, TRUE)",
            (str(tenant_id),),
        )
        return process_range(
            cur,
            tenant_id=tenant_id,
            start_day=start_day,
            end_day=end_day,
            apply=apply,
        )


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _json_result(result: RestorationResult) -> dict[str, Any]:
    return {
        **asdict(result),
        "start_day": result.start_day.isoformat(),
        "end_day": result.end_day.isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure or restore generic evidence for withdrawn historical "
            "Ninja devices; defaults to read-only measurement"
        )
    )
    parser.add_argument("--start-day", type=_date, required=True)
    parser.add_argument("--end-day", type=_date, required=True)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="restore eligible source evidence; omit for read-only measurement",
    )
    args = parser.parse_args()

    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    try:
        result = run(**vars(args))
    except RestorationBlocked as exc:
        parser.exit(2, json.dumps({"error": str(exc)}, sort_keys=True) + "\n")
    except Exception:
        # Database constraint details can contain source identifiers. Keep the
        # operator surface aggregate-only even on an unexpected rollback.
        parser.exit(
            1,
            json.dumps(
                {"error": "historical evidence restoration failed; no rows committed"},
                sort_keys=True,
            )
            + "\n",
        )
    print(json.dumps(_json_result(result), sort_keys=True))


if __name__ == "__main__":
    main()
