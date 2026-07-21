"""Software inventory ingest.

Source:  GET /v2/queries/software  (fleet-wide, cursor-paginated).
Target:  operations.entity_observations  (entity_type='software').

Resolution: ninja device_id (int) → operations device UUID + client UUID
via operations.device_links JOIN operations.devices.

RLS note: operations tables enforce tenant isolation via the
operations.tenant_id GUC.  Every connection that touches operations.*
must SET LOCAL operations.tenant_id = 1 inside its transaction.

After all observations are written, calls
operations.refresh_software_installations_current(1) to materialise
software_installations_current.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Json

from ingest import db
from ingest.observations import write_current_rows
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.ninja_client import NinjaClient
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
        observed_at = datetime.now(timezone.utc)
        batch_id = uuid.uuid4()
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(_GUC)
            run_id = begin_run(
                cur, TENANT_ID, NINJA_SOURCE_BINDING_ID, "Ninja.software",
                observed_at,
            )

        device_map = _load_device_map()
        if not device_map:
            log.warning("inventory.software: no devices in operations.device_links — skipping")
            stats["rows_upserted"] = 0
            return

        log.info("inventory.software: resolved %d devices (df=%r)", len(device_map), df)

        obs_rows: list[dict] = []
        unresolved = 0
        seen = 0

        params = {"df": df} if df else None
        for item in client.paginate_cursor("/queries/software", params=params):
            seen += 1
            ninja_device_id = str(item.get("deviceId", ""))
            resolution = device_map.get(ninja_device_id)
            if resolution is None:
                unresolved += 1
                continue

            ops_device_id, ops_client_id = resolution
            name = (item.get("name") or "").strip()
            if not name:
                continue

            entity_key = name.lower()
            publisher = (item.get("publisher") or "").strip()
            version = (item.get("version") or "").strip()
            location = (item.get("location") or "").strip()

            obs_hash = hashlib.sha256(
                f"{ninja_device_id}:{entity_key}:{version}:{publisher}".encode()
            ).digest()

            obs_rows.append({
                "observation_id": uuid.uuid4(),
                "tenant_id": TENANT_ID,
                "client_id": ops_client_id,
                "device_id": ops_device_id,
                "collector_instance_id": INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id": NINJA_SOURCE_BINDING_ID,
                "entity_type": "software",
                "entity_key": entity_key,
                "platform": "Ninja",
                "subplatform": "",
                "observed_at": observed_at,
                "raw_data": Json(item),
                "canonical_data": Json({
                    "name": name,
                    "publisher": publisher or None,
                    "version": version or None,
                    "location": location or None,
                    "install_date": item.get("installDate"),
                }),
                "batch_id": batch_id,
                "observation_hash": obs_hash,
                "collector_version": "",
                "schema_version": SCHEMA_VERSION,
            })

            if len(obs_rows) >= _BATCH_SIZE:
                _flush(obs_rows, run_id)
                obs_rows.clear()

        if obs_rows:
            _flush(obs_rows, run_id)

        inserted = seen - unresolved
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(_GUC)
            complete_run(cur, run_id, inserted)
            reconcile_complete_run(cur, run_id)

        log.info(
            "inventory.software: seen=%d inserted=%d unresolved=%d",
            seen, inserted, unresolved,
        )
        if unresolved:
            log.warning(
                "inventory.software: %d observations had no matching device_link",
                unresolved,
            )

        stats["rows_upserted"] = inserted
        stats["rows_inserted"] = inserted

        _refresh_current()
        return inserted


def _load_device_map() -> dict[str, tuple[uuid.UUID, uuid.UUID]]:
    """Return {str(ninja_device_id): (ops_device_uuid, ops_client_uuid)}."""
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
        return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _flush(rows: list[dict], run_id: uuid.UUID) -> None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_GUC)
        db.insert_ignore(
            cur,
            "operations.entity_observations",
            rows,
            ["tenant_id", "collector_instance_id", "batch_id", "observation_hash"],
        )
        current_rows = []
        for row in rows:
            current = dict(row)
            current["parent_source_key"] = str(row["device_id"])
            current["last_seen_at"] = row["observed_at"]
            current["last_received_at"] = row["observed_at"]
            current["active"] = True
            current["withdrawn_at"] = None
            current["snapshot_scope"] = "Ninja.software"
            current["last_snapshot_run_id"] = run_id
            current["raw_hash"] = hashlib.sha256(
                str(row["raw_data"]).encode("utf-8")
            ).digest()
            current_rows.append(current)
        write_current_rows(cur, current_rows)


def _refresh_current() -> None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT operations.refresh_software_installations_current(%s)",
            (TENANT_ID,),
        )
    log.info("inventory.software: software_installations_current refreshed")
