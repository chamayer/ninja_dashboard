"""Ninja software inventory with dedicated current state and SCD-2 history.

The legacy observation stream remains a temporary rollback source.  Software
itself is a device-to-product relationship inventory, so it deliberately does
not populate the generic observation current/history tables.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.observations import MATERIAL_HASH_VERSION, material_hash
from ingest.runlog import run_log

log = logging.getLogger(__name__)

TENANT_ID = 1
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
SCHEMA_VERSION = 1
_BATCH_SIZE = 500
_GUC = f"SET LOCAL operations.tenant_id = {TENANT_ID}"


def run(client: NinjaClient, df: str | None = None) -> int:
    domain = "inventory.software.scoped" if df else "inventory.software"
    with run_log(domain) as stats:
        observed_at = datetime.now(UTC)
        batch_id = uuid.uuid4()
        device_map = _load_device_map()
        if not device_map:
            log.warning("inventory.software: no devices in operations.device_links — skipping")
            stats["rows_upserted"] = 0
            return 0

        rows: list[dict] = []
        unresolved = 0
        seen = 0
        for item in client.paginate_cursor("/queries/software", params={"df": df} if df else None):
            seen += 1
            resolution = device_map.get(str(item.get("deviceId", "")))
            name = (item.get("name") or "").strip()
            if resolution is None:
                unresolved += 1
                continue
            if not name:
                continue
            device_id, client_id = resolution
            entity_key = name.lower()
            publisher = (item.get("publisher") or "").strip()
            version = (item.get("version") or "").strip()
            rows.append(
                {
                    "observation_id": uuid.uuid4(),
                    "tenant_id": TENANT_ID,
                    "client_id": client_id,
                    "device_id": device_id,
                    "collector_instance_id": INTERNAL_COLLECTOR_INSTANCE_ID,
                    "source_binding_id": NINJA_SOURCE_BINDING_ID,
                    "entity_type": "software",
                    "entity_key": entity_key,
                    "platform": "Ninja",
                    "subplatform": "",
                    "observed_at": observed_at,
                    "raw_data": Json(item),
                    "canonical_data": Json(
                        {
                            "name": name,
                            "publisher": publisher or None,
                            "version": version or None,
                            "location": (item.get("location") or "").strip() or None,
                            "install_date": item.get("installDate"),
                        }
                    ),
                    "batch_id": batch_id,
                    "observation_hash": hashlib.sha256(
                        f"{item.get('deviceId')}:{entity_key}:{version}:{publisher}".encode()
                    ).digest(),
                    "collector_version": "",
                    "schema_version": SCHEMA_VERSION,
                }
            )
            if len(rows) >= _BATCH_SIZE:
                _flush(rows)
                rows.clear()
        if rows:
            _flush(rows)
        if df is None:
            _reconcile_fleet_snapshot(observed_at)

        inserted = seen - unresolved
        log.info(
            "inventory.software: seen=%d inserted=%d unresolved=%d", seen, inserted, unresolved
        )
        if unresolved:
            log.warning(
                "inventory.software: %d observations had no matching device_link", unresolved
            )
        stats["rows_upserted"] = inserted
        stats["rows_inserted"] = inserted
        return inserted


def _load_device_map() -> dict[str, tuple[uuid.UUID, uuid.UUID]]:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_GUC)
        cur.execute(
            """
            SELECT dl.external_id, dl.device_id, d.client_id
              FROM operations.device_links dl
              JOIN operations.devices d ON d.id = dl.device_id
              JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
             WHERE dl.tenant_id = %s AND d.deleted_at IS NULL
        """,
            (TENANT_ID,),
        )
        return {
            external_id: (device_id, client_id)
            for external_id, device_id, client_id in cur.fetchall()
        }


def _flush(rows: list[dict]) -> None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_GUC)
        db.insert_ignore(
            cur,
            "operations.entity_observations",
            rows,
            ["tenant_id", "collector_instance_id", "batch_id", "observation_hash"],
        )
        _write_installation_current(cur, rows)


def _canonical(row: dict) -> dict:
    value = row["canonical_data"]
    return value.obj if isinstance(value, Json) else value


def _write_installation_current(cur, rows: list[dict]) -> None:
    current_rows: list[dict] = []
    history_rows: list[dict] = []
    latest_rows = {
        (row["tenant_id"], row["client_id"], row["device_id"], row["entity_key"]): row
        for row in rows
    }
    for row in latest_rows.values():
        canonical = _canonical(row)
        material = {
            "publisher": canonical.get("publisher"),
            "version": canonical.get("version"),
            "location": canonical.get("location"),
            "install_date": canonical.get("install_date"),
        }
        content_hash = material_hash(material)
        identity = {
            "tenant_id": row["tenant_id"],
            "client_id": row["client_id"],
            "device_id": row["device_id"],
            "canonical_name": row["entity_key"],
        }
        cur.execute(
            """
            SELECT material_hash, stale_since, deleted_at, deleted_reason
              FROM operations.software_installations_current
             WHERE tenant_id = %(tenant_id)s AND client_id = %(client_id)s
               AND device_id = %(device_id)s AND canonical_name = %(canonical_name)s
             FOR UPDATE
        """,
            identity,
        )
        previous = cur.fetchone()
        changed = previous is None or previous[0] != content_hash or previous[1] is not None
        if changed:
            cur.execute(
                """
                UPDATE operations.software_installation_history
                   SET effective_to = %s, last_seen_at = %s, active = FALSE
                 WHERE tenant_id = %s AND source_binding_id = %s
                   AND device_id = %s AND canonical_name = %s AND effective_to IS NULL
            """,
                (
                    row["observed_at"],
                    row["observed_at"],
                    row["tenant_id"],
                    row["source_binding_id"],
                    row["device_id"],
                    row["entity_key"],
                ),
            )
            history_rows.append(
                {
                    "id": uuid.uuid4(),
                    "tenant_id": row["tenant_id"],
                    "source_binding_id": row["source_binding_id"],
                    "client_id": row["client_id"],
                    "device_id": row["device_id"],
                    "canonical_name": row["entity_key"],
                    "publisher": material["publisher"],
                    "version": material["version"],
                    "install_location": material["location"],
                    "install_date": material["install_date"],
                    "material_hash": content_hash,
                    "hash_algorithm_version": MATERIAL_HASH_VERSION,
                    "effective_from": row["observed_at"],
                    "effective_to": None,
                    "last_seen_at": row["observed_at"],
                    "received_at": row["observed_at"],
                    "active": True,
                }
            )
        else:
            cur.execute(
                """
                UPDATE operations.software_installation_history
                   SET last_seen_at = %s, received_at = %s
                 WHERE tenant_id = %s AND source_binding_id = %s
                   AND device_id = %s AND canonical_name = %s AND effective_to IS NULL
            """,
                (
                    row["observed_at"],
                    row["observed_at"],
                    row["tenant_id"],
                    row["source_binding_id"],
                    row["device_id"],
                    row["entity_key"],
                ),
            )
        current_rows.append(
            {
                **identity,
                "publisher": material["publisher"],
                "version": material["version"],
                "install_location": material["location"],
                "install_date": material["install_date"],
                "first_observed_at": row["observed_at"],
                "last_observed_at": row["observed_at"],
                "refreshed_at": row["observed_at"],
                "stale_since": None,
                "stale_reason": "",
                "deleted_at": None if previous is None else previous[2],
                "deleted_reason": "" if previous is None else previous[3],
                "material_hash": content_hash,
                "hash_algorithm_version": MATERIAL_HASH_VERSION,
            }
        )
    if history_rows:
        db.insert_ignore(cur, "operations.software_installation_history", history_rows, ["id"])
    db.upsert(
        cur,
        "operations.software_installations_current",
        current_rows,
        ["tenant_id", "client_id", "device_id", "canonical_name"],
        [
            "publisher",
            "version",
            "install_location",
            "install_date",
            "last_observed_at",
            "refreshed_at",
            "stale_since",
            "stale_reason",
            "deleted_at",
            "deleted_reason",
            "material_hash",
            "hash_algorithm_version",
        ],
    )


def _reconcile_fleet_snapshot(observed_at: datetime) -> None:
    """Mark only fleet-snapshot absences stale and close their open intervals."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_GUC)
        cur.execute(
            """
            WITH stale AS (
                UPDATE operations.software_installations_current
                   SET stale_since = %s, stale_reason = 'ninja.ingest.complete_snapshot_missing'
                 WHERE tenant_id = %s AND stale_since IS NULL AND deleted_at IS NULL
                   AND last_observed_at < %s
                 RETURNING tenant_id, client_id, device_id, canonical_name
            )
            UPDATE operations.software_installation_history h
               SET effective_to = %s, last_seen_at = %s, active = FALSE
              FROM stale s
             WHERE h.tenant_id = s.tenant_id AND h.source_binding_id = %s
               AND h.client_id = s.client_id AND h.device_id = s.device_id
               AND h.canonical_name = s.canonical_name AND h.effective_to IS NULL
        """,
            (
                observed_at,
                TENANT_ID,
                observed_at,
                observed_at,
                observed_at,
                NINJA_SOURCE_BINDING_ID,
            ),
        )
        stale = cur.rowcount
    log.info("inventory.software: reconciled %d stale installations", stale)
