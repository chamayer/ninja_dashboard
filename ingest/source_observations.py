"""Platform-level source observation writer.

Any source connector that produces entity_observations rows calls through here.
`SourceConfig.source_binding_id` and `SourceConfig.entity_type` drive the write —
no platform-specific branching. Registering a new source means seeding its
operations.source_bindings row; no code changes required here.

Fetchers are the only thing keyed by platform (they are code, not config).
Everything else is config-driven via ingest.sources.

Client resolution order per observation:
  1. Client-scoped source instance (SourceConfig.client_id) — e.g. per-client
     ScreenConnect instances.
  2. client_links lookup on (source, platform_group_id) — e.g. S1 site id,
     LMI group id.
  3. Resolved device's client (fallback, requires identity match).
Groups that resolve no client are recorded in
operations.unmatched_source_groups for operator review.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.connectors import logmein, screenconnect, sentinelone
from ingest.identity.fast_path import resolve_device_fast
from ingest.normalize import is_placeholder_org_name, os_family
from ingest.sources import SourceConfig

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
            _record_source_run(source, observed_at, ok=True, rows=written)
            log.info(
                "source_observations: source=%s written=%d", source.source_name, written
            )
        except Exception as exc:
            _record_source_run(
                source, observed_at, ok=False, rows=0, error=str(exc)[:2000]
            )
            log.exception(
                "source_observations: source %s failed — continuing", source.source_name
            )
    return counts


def _record_source_run(
    source: SourceConfig, started_at: datetime, ok: bool, rows: int, error: str = ""
) -> None:
    """Record the source run in operations.run_log (evaluator source guard)."""
    kind = f"source.{source.platform}.{source.source_key}".rstrip(".")[:80]
    try:
        with db.transaction() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
            cur.execute(
                """
                INSERT INTO operations.run_log
                    (id, tenant_id, kind, subject_ref, started_at, ended_at,
                     ok, rows, error)
                VALUES (gen_random_uuid(), %s, %s, '{}'::jsonb,
                        %s, NOW(), %s, %s, %s)
                """,
                (_TENANT_ID, kind, started_at, ok, rows, error),
            )
    except Exception:
        log.exception("source_observations: run_log write failed — continuing")


def _load_client_links(cur, source: SourceConfig) -> dict[str, uuid.UUID]:
    """Return {external_id: client_id} for this source's client_links."""
    if not source.ops_source_id:
        return {}
    cur.execute(
        """
        SELECT external_id, client_id
        FROM operations.client_links
        WHERE tenant_id = %s AND source_id = %s
        """,
        (_TENANT_ID, source.ops_source_id),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _upsert_client_links(
    cur,
    source: SourceConfig,
    resolved_groups: dict[str, tuple[uuid.UUID, str]],
) -> None:
    """Ensure a client_links row exists per resolved source group.

    Per-client sources (is_shared=False, e.g. ScreenConnect-UTA): external_id
    is the source_key — one stable row per source instance.
    Shared sources (is_shared=True, e.g. SentinelOne, LogMeIn): external_id
    is the platform group id (S1 site id, LMI group id) so the mapping
    survives group renames.

    The link is the source of truth once created: on conflict only
    external_name refreshes; client_id is never reassigned by ingest.
    """
    if not source.ops_source_id:
        return
    for group_id, (client_uuid, group_name) in resolved_groups.items():
        external_id = source.source_key if not source.is_shared else group_id
        if not external_id:
            continue
        external_name = group_name or source.source_name
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


def _record_unmatched_groups(
    cur,
    source: SourceConfig,
    unmatched: dict[str, tuple[str, int]],
) -> None:
    """Upsert operator-review rows for source groups that resolved no client."""
    if not source.ops_source_id:
        return
    for group_id, (group_name, device_count) in unmatched.items():
        if is_placeholder_org_name(group_name):
            continue
        cur.execute(
            """
            INSERT INTO operations.unmatched_source_groups
                (tenant_id, source_id, external_id, external_name, device_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_id, external_id)
            DO UPDATE SET
                external_name = COALESCE(NULLIF(EXCLUDED.external_name, ''),
                                         operations.unmatched_source_groups.external_name),
                device_count  = EXCLUDED.device_count,
                last_seen_at  = now()
            """,
            (_TENANT_ID, source.ops_source_id, group_id, group_name or "", device_count),
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
    resolved_groups: dict[str, tuple[uuid.UUID, str]] = {}  # group_id → (client, name)
    unmatched_groups: dict[str, tuple[str, int]] = {}       # group_id → (name, count)
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        link_map = _load_client_links(cur, source)
        for row in rows:
            entity_key = str(row.get("platform_device_id") or "")
            if not entity_key:
                continue
            hostname = row.get("hostname") or ""
            raw = row.get("raw_data") or {}
            if isinstance(raw, Json):
                raw = raw.obj  # connectors wrap payloads for the legacy writer
            if not isinstance(raw, dict):
                raw = {}
            serial = (
                raw.get("serialNumber")
                or raw.get("biosSerialNumber")
                or raw.get("serial_number")
                or None
            )
            os_name = row.get("os_name") or None
            canonical_data: dict[str, Any] = {
                "hostname":      hostname,
                "platform":      source.platform,
                "last_seen_at":  (
                    row["last_seen_at"].isoformat() if row.get("last_seen_at") else None
                ),
                "is_online":     row.get("is_online"),
                "serial_number": serial,
                # None when the source gives no explicit signal — never guessed.
                "device_type":   row.get("device_type"),
                "os_name":       os_name,
                "os_family":     os_family(os_name),
                "domain":        row.get("domain_name"),
            }
            if raw.get("IsDup") is not None:
                canonical_data["is_dup"] = bool(raw["IsDup"])
            obs_hash = hashlib.sha256(
                f"{entity_key}:{observed_at.isoformat()}".encode()
            ).digest()

            device_id = resolve_device_fast(
                cur, _TENANT_ID, source.platform, entity_key,
                serial=serial,
                hostname=hostname or None,
            )

            group_id = str(row.get("platform_group_id") or "").strip()
            group_name = (row.get("platform_group_name") or "").strip()

            # 1. Client-scoped instance wins.
            client_id = source.client_id
            # 2. client_links mapping on the source group.
            if client_id is None and group_id:
                client_id = link_map.get(group_id)
            # 3. Fall back to the resolved device's client.
            if client_id is None and device_id:
                cur.execute(
                    "SELECT client_id FROM operations.devices"
                    " WHERE id = %s AND deleted_at IS NULL",
                    (device_id,),
                )
                dev_row = cur.fetchone()
                client_id = dev_row[0] if dev_row else None

            if group_id or not source.is_shared:
                if client_id:
                    resolved_groups[group_id] = (client_id, group_name)
                elif group_id:
                    name, count = unmatched_groups.get(group_id, (group_name, 0))
                    unmatched_groups[group_id] = (name or group_name, count + 1)

            obs_rows.append({
                "observation_id":        uuid.uuid4(),
                "tenant_id":             _TENANT_ID,
                "client_id":             client_id,
                "device_id":             device_id,
                "collector_instance_id": _INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id":     source.source_binding_id,
                "entity_type":           source.entity_type,
                "entity_key":            entity_key,
                "platform":              source.platform,
                "subplatform":           "",
                "observed_at":           observed_at,
                "raw_data":              Json(raw),
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
            # A group is unmatched only if NO row in the batch resolved it.
            for gid in resolved_groups:
                unmatched_groups.pop(gid, None)
            _upsert_client_links(cur, source, resolved_groups)
            _record_unmatched_groups(cur, source, unmatched_groups)
    return len(obs_rows)
