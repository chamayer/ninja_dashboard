"""Patch findings emitter — Track 5.

Reads ninja_patches.patch_facts and emits per-device (or per-client)
findings per BLUEPRINT §5.1:

  * device_never_patched
  * patching_stalled (>35d without a fresh patch state)
  * patch_failing_repeatedly (same KB failing ≥3 times per device)
  * patch_approval_backlog (subject=client)

`reboot_pending` from the blueprint isn't emitted here — patch_facts
doesn't carry a distinct reboot-pending status yet; parked to backlog
until the connector projects one.

All emitted findings map ninja_core.devices.id → operations.devices
via device_links (source=Ninja). Devices we can't map are silently
skipped (they're not in the ops universe yet).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from ingest import db

log = logging.getLogger(__name__)

_TENANT_ID = 1
_STALLED_DAYS = 35
_FAILING_RUN_COUNT = 3


def classify(tenant_id: int = _TENANT_ID) -> int:
    now = datetime.now(timezone.utc)
    error: str | None = None
    affected = 0
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
            ft_ids = _finding_type_ids(cur)

            emitted_keys: set[str] = set()

            affected += _emit_never_patched(cur, tenant_id, ft_ids, now, emitted_keys)
            affected += _emit_patching_stalled(cur, tenant_id, ft_ids, now, emitted_keys)
            affected += _emit_failing_repeatedly(cur, tenant_id, ft_ids, now, emitted_keys)
            affected += _emit_approval_backlog(cur, tenant_id, ft_ids, now, emitted_keys)

            _auto_resolve(cur, tenant_id, emitted_keys, now)
    except Exception as exc:
        error = str(exc)[:2000]
        raise
    finally:
        try:
            with db.transaction() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
                cur.execute(
                    """
                    INSERT INTO operations.run_log
                        (id, tenant_id, kind, subject_ref, started_at,
                         ended_at, ok, rows, error)
                    VALUES (gen_random_uuid(), %s, 'patch_findings',
                            '{}'::jsonb, %s, NOW(), %s, %s, %s)
                    """,
                    (tenant_id, now, error is None, affected, error or ""),
                )
        except Exception:
            log.exception("patch_findings: run_log write failed")
    log.info("patch_findings: tenant=%d affected=%d", tenant_id, affected)
    return affected


def _finding_type_ids(cur) -> dict[str, int]:
    cur.execute(
        """
        SELECT name, id FROM operations.finding_types
        WHERE name IN (
            'device_never_patched', 'patching_stalled',
            'patch_failing_repeatedly', 'patch_approval_backlog'
        )
        """
    )
    return {n: i for n, i in cur.fetchall()}


def _emit_never_patched(cur, tenant_id, ft_ids, now, keys) -> int:
    ft_id = ft_ids.get("device_never_patched")
    if not ft_id:
        return 0
    cur.execute(
        """
        WITH linked AS (
            SELECT d.id AS device_id, d.client_id, d.canonical_hostname,
                   dl.external_id::int AS ninja_id
            FROM operations.devices d
            JOIN operations.device_links dl
              ON dl.device_id = d.id AND dl.tenant_id = d.tenant_id
            JOIN operations.sources s ON s.id = dl.source_id AND s.name='Ninja'
            WHERE d.tenant_id = %s AND d.deleted_at IS NULL
              AND d.lifecycle_status <> 'retired'
        )
        SELECT l.device_id, l.client_id, l.canonical_hostname
        FROM linked l
        WHERE NOT EXISTS(
            SELECT 1 FROM ninja_patches.patch_facts pf
            WHERE pf.device_id = l.ninja_id AND pf.status = 'INSTALLED'
        )
        """,
        (tenant_id,),
    )
    count = 0
    for dev_id, client_id, hostname in cur.fetchall():
        count += _upsert(
            cur, tenant_id, ft_id, client_id, dev_id, "device",
            "device_never_patched", "", "high", now,
            {"hostname": hostname, "reason": "no INSTALLED patches on record"},
            keys,
        )
    return count


def _emit_patching_stalled(cur, tenant_id, ft_ids, now, keys) -> int:
    ft_id = ft_ids.get("patching_stalled")
    if not ft_id:
        return 0
    cur.execute(
        f"""
        WITH latest AS (
            SELECT pf.device_id, MAX(pf.last_observed_at) AS last_seen
            FROM ninja_patches.patch_facts pf
            GROUP BY pf.device_id
        )
        SELECT d.id, d.client_id, d.canonical_hostname, l.last_seen
        FROM latest l
        JOIN operations.device_links dl
          ON dl.external_id::int = l.device_id AND dl.tenant_id = %s
        JOIN operations.sources s ON s.id = dl.source_id AND s.name='Ninja'
        JOIN operations.devices d
          ON d.id = dl.device_id AND d.deleted_at IS NULL
             AND d.lifecycle_status <> 'retired'
        WHERE l.last_seen < NOW() - INTERVAL '{_STALLED_DAYS} days'
        """,
        (tenant_id,),
    )
    count = 0
    for dev_id, client_id, hostname, last_seen in cur.fetchall():
        count += _upsert(
            cur, tenant_id, ft_id, client_id, dev_id, "device",
            "patching_stalled", "", "medium", now,
            {
                "hostname": hostname,
                "last_patch_seen_at": last_seen.isoformat() if last_seen else None,
                "threshold_days": _STALLED_DAYS,
            },
            keys,
        )
    return count


def _emit_failing_repeatedly(cur, tenant_id, ft_ids, now, keys) -> int:
    ft_id = ft_ids.get("patch_failing_repeatedly")
    if not ft_id:
        return 0
    cur.execute(
        f"""
        SELECT pf.device_id, pf.kb_number, COUNT(*) AS fails
        FROM ninja_patches.patch_facts pf
        WHERE pf.status = 'FAILED' AND pf.kb_number IS NOT NULL
        GROUP BY pf.device_id, pf.kb_number
        HAVING COUNT(*) >= {_FAILING_RUN_COUNT}
        """
    )
    grouped: dict[int, list[tuple[str, int]]] = {}
    for nid, kb, fails in cur.fetchall():
        grouped.setdefault(nid, []).append((kb, fails))
    if not grouped:
        return 0
    cur.execute(
        """
        SELECT dl.external_id::int, d.id, d.client_id, d.canonical_hostname
        FROM operations.device_links dl
        JOIN operations.sources s ON s.id = dl.source_id AND s.name='Ninja'
        JOIN operations.devices d
          ON d.id = dl.device_id AND d.deleted_at IS NULL
             AND d.lifecycle_status <> 'retired'
        WHERE dl.tenant_id = %s
        """,
        (tenant_id,),
    )
    id_map = {nid: (dev, client, host) for nid, dev, client, host in cur.fetchall()}
    count = 0
    for nid, kb_list in grouped.items():
        mapped = id_map.get(nid)
        if not mapped:
            continue
        dev_id, client_id, hostname = mapped
        # Emit ONE finding per device (details lists all failing KBs).
        count += _upsert(
            cur, tenant_id, ft_id, client_id, dev_id, "device",
            "patch_failing_repeatedly", "", "high", now,
            {
                "hostname": hostname,
                "failing_patches": [
                    {"kb": kb, "fail_count": fails}
                    for kb, fails in sorted(kb_list, key=lambda x: -x[1])
                ][:20],
            },
            keys,
        )
    return count


def _emit_approval_backlog(cur, tenant_id, ft_ids, now, keys) -> int:
    """Per-client: how many APPROVED patches are not yet installed anywhere?"""
    ft_id = ft_ids.get("patch_approval_backlog")
    if not ft_id:
        return 0
    cur.execute(
        """
        WITH approved_latest AS (
            SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
                   pf.device_id, pf.patch_uid, pf.status
            FROM ninja_patches.patch_facts pf
            ORDER BY pf.device_id, pf.patch_uid, pf.last_observed_at DESC
        )
        SELECT d.client_id, c.display_name,
               COUNT(*) AS backlog
        FROM approved_latest a
        JOIN operations.device_links dl
          ON dl.external_id::int = a.device_id AND dl.tenant_id = %s
        JOIN operations.sources s ON s.id = dl.source_id AND s.name='Ninja'
        JOIN operations.devices d
          ON d.id = dl.device_id AND d.deleted_at IS NULL
             AND d.lifecycle_status <> 'retired'
        JOIN operations.clients c ON c.id = d.client_id AND c.deleted_at IS NULL
        WHERE a.status = 'APPROVED'
        GROUP BY d.client_id, c.display_name
        HAVING COUNT(*) >= 25
        """,
        (tenant_id,),
    )
    count = 0
    for client_id, display_name, backlog in cur.fetchall():
        count += _upsert(
            cur, tenant_id, ft_id, client_id, client_id, "client",
            "patch_approval_backlog", "", "medium", now,
            {"client_name": display_name, "backlog_count": backlog},
            keys,
        )
    return count


def _condition_key(tenant_id, client_id, subject_id, ft_name: str, extra: str) -> str:
    raw = f"{tenant_id}:{client_id}:{subject_id}:{ft_name}:{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _upsert(cur, tenant_id, ft_id, client_id, subject_id, subject_type,
            ft_name, extra_key, severity, now, details, emitted_keys) -> int:
    ckey = _condition_key(tenant_id, client_id, subject_id, ft_name, extra_key)
    if ckey in emitted_keys:
        return 0
    emitted_keys.add(ckey)
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            %s, %s, %s::jsonb,
            %s, %s, 'confirmed', 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_seen_at     = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            finding_details  = EXCLUDED.finding_details,
            status           = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        """,
        (
            tenant_id, ft_id, client_id,
            subject_type, subject_id, json.dumps(details),
            ckey, severity, now, now, now,
        ),
    )
    return 1


def _auto_resolve(cur, tenant_id, emitted_keys, now) -> None:
    cur.execute(
        """
        UPDATE operations.findings f
        SET status = 'resolved', last_seen_at = %s
        FROM operations.finding_types ft
        WHERE ft.id = f.finding_type_id
          AND ft.source_module = 'platform.patch_findings'
          AND f.tenant_id = %s
          AND f.status IN ('open', 'acknowledged')
          AND NOT (f.condition_key = ANY(%s::text[]))
        """,
        (now, tenant_id, list(emitted_keys) if emitted_keys else [""]),
    )
