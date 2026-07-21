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

Containers are entities too (BLUEPRINT Track C): every source group seen in
a run is written as one `org` observation keyed by its stable group id.
Fetchers may return container-only rows (`_org_only: True` with
platform_group_id/platform_group_name) so groups with zero devices are
still observed.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.observations import write_current_rows
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.connectors import logmein, screenconnect, sentinelone
from ingest.identity.fast_path import resolve_device_fast
from ingest.normalize import (
    extract_macs,
    normalize_hostname,
    normalize_org_name,
    os_family,
)
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


def _load_placeholder_names(cur) -> set[str]:
    """Placeholder container names live in data (Track C principle 4)."""
    cur.execute(
        "SELECT normalized_name FROM operations.placeholder_org_names"
        " WHERE tenant_id = %s",
        (_TENANT_ID,),
    )
    return {row[0] for row in cur.fetchall()}


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
    placeholder_names: set[str],
) -> None:
    """Upsert operator-review rows for source groups that resolved no client."""
    if not source.ops_source_id:
        return
    for group_id, (group_name, device_count) in unmatched.items():
        if normalize_org_name(group_name) in placeholder_names:
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
    all_groups: dict[str, list] = {}                        # group_id → [name, count]
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        snapshot_scope = source.source_key or source.source_name
        run_id = begin_run(
            cur, _TENANT_ID, source.source_binding_id, snapshot_scope,
            observed_at, expected_rows=len(rows),
        )
        link_map = _load_client_links(cur, source)
        placeholder_names = _load_placeholder_names(cur)
        for row in rows:
            if row.get("_org_only"):
                # Container-only record (e.g. a group with zero devices) —
                # registers the group for the org observation, no device row.
                gid = str(row.get("platform_group_id") or "").strip()
                gname = (row.get("platform_group_name") or "").strip()
                if gid and gid not in all_groups:
                    all_groups[gid] = [gname, 0]
                continue
            entity_key = str(row.get("platform_device_id") or "")
            if not entity_key:
                continue
            hostname = row.get("hostname") or ""
            raw = row.get("raw_data") or {}
            if isinstance(raw, Json):
                raw = raw.obj  # connectors wrap payloads for the legacy writer
            if not isinstance(raw, dict):
                raw = {}
            guest_info = raw.get("GuestInfo") if isinstance(raw.get("GuestInfo"), dict) else {}
            serial = (
                raw.get("serialNumber")
                or raw.get("biosSerialNumber")
                or raw.get("serial_number")
                or guest_info.get("MachineSerialNumber")
                or None
            )
            os_name = row.get("os_name") or None
            canonical_data: dict[str, Any] = {
                "hostname":      hostname,
                "platform":      source.platform,
                "entity_type":   source.entity_type,
                # platform_group_id lets the client resolver backfill
                # device observations once the org attaches to a client.
                "platform_group_id": str(row.get("platform_group_id") or ""),
                "last_seen_at":  (
                    row["last_seen_at"].isoformat() if row.get("last_seen_at") else None
                ),
                "is_online":     row.get("is_online"),
                "serial_number": serial,
                "macs":          extract_macs(raw),
                # None when the source gives no explicit signal — never guessed.
                "device_role":   row.get("device_type"),
                "os_name":       os_name,
                "os_family":     os_family(os_name),
                "domain":        row.get("domain_name"),
            }
            if raw.get("IsDup") is not None:
                canonical_data["is_dup"] = bool(raw["IsDup"])
            obs_hash = hashlib.sha256(
                f"{entity_key}:{observed_at.isoformat()}".encode()
            ).digest()

            group_id = str(row.get("platform_group_id") or "").strip()
            group_name = (row.get("platform_group_name") or "").strip()

            # 1. Client-scoped instance wins.
            client_id = source.client_id
            # 2. client_links mapping on the source group.
            if client_id is None and group_id:
                client_id = link_map.get(group_id)

            device_id = resolve_device_fast(
                cur, _TENANT_ID, source.platform, entity_key,
                entity_type=source.entity_type,
                serial=serial,
                hostname=normalize_hostname(hostname) or None,
                client_id=client_id,
            )
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
            if group_id:
                entry = all_groups.setdefault(group_id, [group_name, 0])
                entry[0] = entry[0] or group_name
                entry[1] += 1

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

        # One `org` observation per container per run (BLUEPRINT Track C.2).
        # entity_key = stable group id (never the display name). Attachment
        # here is rung 1 only (existing id-link / client-scoped instance);
        # rungs 2-4 belong to the client resolver (C2).
        device_row_count = len(obs_rows)
        if not source.is_shared:
            org_containers = {
                source.source_key or source.source_name: [
                    source.source_name, device_row_count
                ]
            }
        else:
            org_containers = all_groups
        for gid, (gname, gcount) in org_containers.items():
            if not gid:
                continue
            org_client_id = (
                source.client_id if not source.is_shared else link_map.get(gid)
            )
            normalized = normalize_org_name(gname)
            obs_rows.append({
                "observation_id":        uuid.uuid4(),
                "tenant_id":             _TENANT_ID,
                "client_id":             org_client_id,
                "device_id":             None,
                "collector_instance_id": _INTERNAL_COLLECTOR_INSTANCE_ID,
                "source_binding_id":     source.source_binding_id,
                "entity_type":           "org",
                "entity_key":            gid,
                "platform":              source.platform,
                "subplatform":           "",
                "observed_at":           observed_at,
                "raw_data":              Json({}),
                "canonical_data":        Json({
                    "name":            gname,
                    "normalized_name": normalized,
                    "platform":        source.platform,
                    "entity_type":     "org",
                    "device_count":    gcount,
                    "is_placeholder":  normalized in placeholder_names,
                }),
                "batch_id":              batch_id,
                # entity_type prefixed so an org key can never collide with a
                # device key in the same batch.
                "observation_hash":      hashlib.sha256(
                    f"org:{gid}:{observed_at.isoformat()}".encode()
                ).digest(),
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
            # Dual-write the bounded current-state table. History/reconciliation
            # is enabled only after the complete-snapshot ledger is wired.
            current_rows = []
            for row in obs_rows:
                current = dict(row)
                current["parent_source_key"] = ""
                current["last_seen_at"] = row["observed_at"]
                current["last_received_at"] = row["observed_at"]
                current["active"] = True
                current["withdrawn_at"] = None
                current["snapshot_scope"] = snapshot_scope
                current["last_snapshot_run_id"] = run_id
                current["raw_hash"] = hashlib.sha256(
                    str(row["raw_data"]).encode("utf-8")
                ).digest()
                current_rows.append(current)
            write_current_rows(cur, current_rows)
        complete_run(cur, run_id, len(obs_rows))
        if not getattr(source, "is_partial_snapshot", False):
            reconcile_complete_run(cur, run_id)
            # A group is unmatched only if NO row in the batch resolved it.
            for gid in resolved_groups:
                unmatched_groups.pop(gid, None)
            _upsert_client_links(cur, source, resolved_groups)
            _record_unmatched_groups(cur, source, unmatched_groups, placeholder_names)
    return len(obs_rows)
