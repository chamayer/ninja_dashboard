"""Platform-level source observation writer.

Any source connector that produces entity_observations rows calls through here.
`SourceConfig.source_binding_id` and `SourceConfig.entity_type` drive the write —
no platform-specific branching. Registering a new source means seeding its
operations.source_bindings row; no code changes required here.

Fetchers are the only thing keyed by platform (they are code, not config).
When a source moves its fetcher out of agent_compliance/clients/, update the
_FETCHERS dict below. Everything else is config-driven.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.agent_compliance.clients import logmein, screenconnect, sentinelone
from ingest.agent_compliance.config_loader import SourceConfig
from ingest.identity.fast_path import resolve_device_fast

log = logging.getLogger(__name__)

_TENANT_ID = 1
_INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

_FETCHERS = {
    "SentinelOne":   sentinelone.fetch,
    "ScreenConnect": screenconnect.fetch,
    "LogMeIn":       logmein.fetch,
}


def run_source_observations(
    sources: list[SourceConfig],
    observed_at: datetime,
) -> dict[str, int]:
    """Fetch all registered sources and write to entity_observations.

    Sources with no fetcher registered or no source_binding_id are skipped.
    Per-source exceptions are isolated so one bad source never blocks others.
    Returns counts written per platform.
    """
    batch_id = uuid.uuid4()
    counts: dict[str, int] = {}
    for source in sources:
        if source.platform not in _FETCHERS:
            continue
        if not source.source_binding_id or not source.entity_type:
            log.warning(
                "source_observations: %s has no operations binding — skipping",
                source.source_name,
            )
            continue
        try:
            rows = _FETCHERS[source.platform](source, observed_at)
            written = _write_observations(source, rows, batch_id, observed_at)
            counts[source.platform] = counts.get(source.platform, 0) + written
            log.info(
                "source_observations: source=%s written=%d", source.source_name, written
            )
        except Exception:
            log.exception(
                "source_observations: source %s failed — continuing", source.source_name
            )
    return counts


def _upsert_client_links(
    cur,
    source: SourceConfig,
    obs_rows: list[dict],
    client_group_map: dict,
) -> None:
    """Ensure a client_links row exists for every client seen in this batch.

    Per-client sources (is_shared=False, e.g. ScreenConnect-UTA): external_id
    is the source_key — one stable row per source instance.
    Shared sources (is_shared=True, e.g. SentinelOne, LogMeIn): external_id
    is the client UUID so each client gets its own row under the same source.

    external_name is the client's name as seen in the source system
    (S1 site name, LMI group name, SC client name), taken from the
    platform_group_name field of the original fetcher rows.
    """
    if not source.ops_source_id:
        return
    seen_clients = {
        row["client_id"] for row in obs_rows if row.get("client_id") is not None
    }
    if not seen_clients:
        return
    for client_uuid in seen_clients:
        external_id = (
            source.source_key if not source.is_shared else str(client_uuid)
        )
        external_name = client_group_map.get(client_uuid) or source.source_name
        cur.execute(
            """
            INSERT INTO operations.client_links
                (id, version, tenant_id, client_id, source_id, external_id, external_name)
            VALUES (gen_random_uuid(), 0, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_id, external_id)
            DO UPDATE SET external_name = EXCLUDED.external_name
            """,
            (_TENANT_ID, client_uuid, source.ops_source_id, external_id, external_name),
        )


def _write_observations(
    source: SourceConfig,
    rows: list[dict[str, Any]],
    batch_id: uuid.UUID,
    observed_at: datetime,
) -> int:
    if not rows:
        return 0

    obs_rows: list[dict[str, Any]] = []
    client_group_map: dict = {}  # client_uuid → platform_group_name from source
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        for row in rows:
            entity_key = str(row.get("platform_device_id") or "")
            if not entity_key:
                continue
            hostname = row.get("hostname") or ""
            raw = row.get("raw_data") or {}
            if not isinstance(raw, dict):
                raw = {}
            serial = (
                raw.get("serialNumber")
                or raw.get("biosSerialNumber")
                or raw.get("serial_number")
                or None
            )
            canonical_data: dict[str, Any] = {
                "hostname":      hostname,
                "platform":      source.platform,
                "last_seen_at":  (
                    row["last_seen_at"].isoformat() if row.get("last_seen_at") else None
                ),
                "is_online":     row.get("is_online"),
                "serial_number": serial,
            }
            obs_hash = hashlib.sha256(
                f"{entity_key}:{observed_at.isoformat()}".encode()
            ).digest()

            device_id = resolve_device_fast(
                cur, _TENANT_ID, source.platform, entity_key,
                serial=serial,
                hostname=hostname or None,
            )
            device_client_id = None
            if device_id:
                cur.execute(
                    "SELECT client_id FROM operations.devices"
                    " WHERE id = %s AND deleted_at IS NULL",
                    (device_id,),
                )
                dev_row = cur.fetchone()
                device_client_id = dev_row[0] if dev_row else None

            if device_client_id:
                group_name = (row.get("platform_group_name") or "").strip()
                if group_name:
                    client_group_map[device_client_id] = group_name

            obs_rows.append({
                "observation_id":        uuid.uuid4(),
                "tenant_id":             _TENANT_ID,
                "client_id":             device_client_id,
                "device_id":             device_id,
                "collector_instance_id": _INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id":     source.source_binding_id,
                "entity_type":           source.entity_type,
                "entity_key":            entity_key,
                "platform":              source.platform,
                "subplatform":           "",
                "observed_at":           observed_at,
                "raw_data":              Json({}),
                "canonical_data":        Json(canonical_data),
                "batch_id":              batch_id,
                "observation_hash":      obs_hash,
                "collector_version":     "",
                "schema_version":        1,
            })

        if obs_rows:
            db.insert_ignore(
                cur,
                "operations.entity_observations",
                obs_rows,
                conflict_keys=[
                    "tenant_id", "collector_instance_id", "batch_id", "observation_hash"
                ],
            )
            _upsert_client_links(cur, source, obs_rows, client_group_map)
    return len(obs_rows)
