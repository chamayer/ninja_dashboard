"""Patch findings emitter — Track 5 + Track O batch O5.

Reads `ninja_patches.device_patch_signal` (canonical rollup, matches
Metabase counts) for never_patched / patching_stalled, and
`ninja_patches.patch_facts` for per-KB failure detail and approval
backlog. Every emitter filters subjects on
`operations.v_device.effective_patching_scope = 'Included'` — the
per-domain scope layer built in Track O batch O4 replaces legacy
`ninja_core.v_active_devices` as the population source.

Five finding types (BLUEPRINT §5.1):

  * `device_never_patched` — device with a Ninja link is in scope but
    device_patch_signal.ever_installed = FALSE (never observed an
    INSTALLED row). Mutually exclusive with patching_stalled.
  * `patching_stalled` — device_patch_signal.ever_installed = TRUE but
    last_seen_at is >35 days old (or NULL — old installs with no
    installedAt). Mutually exclusive with never_patched.
  * `reboot_pending` — v_device.needs_reboot = TRUE AND last_boot_at
    older than 3 days (last_boot_at from Ninja device_snapshots via
    device_session_current).
  * `patch_failing_repeatedly` — same KB has failed >=3 times on a
    device that is in scope.
  * `patch_approval_backlog` — subject = client; >=25 APPROVED
    uninstalled patches across the client's in-scope devices.

Multi-Ninja-link ops devices are collapsed via aggregation before
emission (BOOL_OR / MAX / SUM) — same E.3 gotcha handled in O1/O3/O4.
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
_REBOOT_PENDING_DAYS = 3
_FAILING_RUN_COUNT = 3
_APPROVAL_BACKLOG_THRESHOLD = 25


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
            affected += _emit_reboot_pending(cur, tenant_id, ft_ids, now, emitted_keys)
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
            'device_never_patched', 'patching_stalled', 'reboot_pending',
            'patch_failing_repeatedly', 'patch_approval_backlog'
        )
        """
    )
    return {n: i for n, i in cur.fetchall()}


# ─────────────────────────────────────────────────────────────────────
# Per-device patch signal rollup, filtered to in-scope devices.
# Aggregates across multi-Ninja-link ops devices (BOOL_OR / MAX).
# ─────────────────────────────────────────────────────────────────────


_INSCOPE_SIGNAL_CTE = """
    WITH per_device AS (
        SELECT
            dl.tenant_id,
            dl.device_id AS ops_device_id,
            BOOL_OR(COALESCE(dps.ever_installed, FALSE))       AS any_ever_installed,
            MAX(dps.last_seen_at)                              AS max_last_seen_at,
            COUNT(*) FILTER (WHERE dps.device_id IS NOT NULL)  AS signal_rows
        FROM operations.device_links dl
        JOIN operations.sources s
          ON s.id = dl.source_id AND s.name = 'Ninja'
        LEFT JOIN ninja_patches.device_patch_signal dps
          ON dps.device_id = dl.external_id::int
        WHERE dl.tenant_id = %s
        GROUP BY dl.tenant_id, dl.device_id
    )
"""


def _emit_never_patched(cur, tenant_id, ft_ids, now, keys) -> int:
    ft_id = ft_ids.get("device_never_patched")
    if not ft_id:
        return 0
    cur.execute(
        _INSCOPE_SIGNAL_CTE
        + """
        SELECT v.device_id, v.client_id, v.canonical_hostname
        FROM operations.v_device v
        JOIN per_device pd
          ON pd.ops_device_id = v.device_id AND pd.tenant_id = v.tenant_id
        WHERE v.tenant_id = %s
          AND v.effective_patching_scope = 'Included'
          AND v.lifecycle_status <> 'retired'
          AND pd.any_ever_installed = FALSE
        """,
        (tenant_id, tenant_id),
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
        _INSCOPE_SIGNAL_CTE
        + f"""
        SELECT v.device_id, v.client_id, v.canonical_hostname,
               pd.max_last_seen_at
        FROM operations.v_device v
        JOIN per_device pd
          ON pd.ops_device_id = v.device_id AND pd.tenant_id = v.tenant_id
        WHERE v.tenant_id = %s
          AND v.effective_patching_scope = 'Included'
          AND v.lifecycle_status <> 'retired'
          AND pd.any_ever_installed = TRUE
          AND (pd.max_last_seen_at IS NULL
               OR pd.max_last_seen_at < NOW() - INTERVAL '{_STALLED_DAYS} days')
        """,
        (tenant_id, tenant_id),
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


def _emit_reboot_pending(cur, tenant_id, ft_ids, now, keys) -> int:
    """5th finding type per BLUEPRINT §5.1 — device needs reboot AND
    hasn't rebooted in >3 days. Reads v_device (needs_reboot +
    last_boot_at from device_session_current).
    """
    ft_id = ft_ids.get("reboot_pending")
    if not ft_id:
        return 0
    cur.execute(
        f"""
        SELECT v.device_id, v.client_id, v.canonical_hostname,
               v.last_boot_at
        FROM operations.v_device v
        WHERE v.tenant_id = %s
          AND v.effective_patching_scope = 'Included'
          AND v.lifecycle_status <> 'retired'
          AND v.needs_reboot = TRUE
          AND (v.last_boot_at IS NULL
               OR v.last_boot_at < NOW() - INTERVAL '{_REBOOT_PENDING_DAYS} days')
        """,
        (tenant_id,),
    )
    count = 0
    for dev_id, client_id, hostname, last_boot in cur.fetchall():
        count += _upsert(
            cur, tenant_id, ft_id, client_id, dev_id, "device",
            "reboot_pending", "", "medium", now,
            {
                "hostname": hostname,
                "last_boot_at": last_boot.isoformat() if last_boot else None,
                "threshold_days": _REBOOT_PENDING_DAYS,
            },
            keys,
        )
    return count


def _emit_failing_repeatedly(cur, tenant_id, ft_ids, now, keys) -> int:
    """Per-KB failure count on in-scope devices. Emits ONE finding per
    device (details list all failing KBs).
    """
    ft_id = ft_ids.get("patch_failing_repeatedly")
    if not ft_id:
        return 0
    cur.execute(
        f"""
        WITH included AS (
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   dl.external_id::int AS ninja_id,
                   v.client_id, v.canonical_hostname
            FROM operations.v_device v
            JOIN operations.device_links dl
              ON dl.device_id = v.device_id AND dl.tenant_id = v.tenant_id
            JOIN operations.sources s
              ON s.id = dl.source_id AND s.name = 'Ninja'
            WHERE v.tenant_id = %s
              AND v.effective_patching_scope = 'Included'
              AND v.lifecycle_status <> 'retired'
        ),
        failing AS (
            SELECT i.ops_device_id, i.client_id, i.canonical_hostname,
                   pf.kb_number, COUNT(*) AS fails
            FROM ninja_patches.patch_facts pf
            JOIN included i ON i.ninja_id = pf.device_id
            WHERE pf.status = 'FAILED' AND pf.kb_number IS NOT NULL
            GROUP BY i.ops_device_id, i.client_id, i.canonical_hostname, pf.kb_number
            HAVING COUNT(*) >= {_FAILING_RUN_COUNT}
        )
        SELECT ops_device_id, client_id, canonical_hostname,
               jsonb_agg(jsonb_build_object('kb', kb_number, 'fail_count', fails)
                         ORDER BY fails DESC) AS failing_patches
        FROM failing
        GROUP BY ops_device_id, client_id, canonical_hostname
        """,
        (tenant_id,),
    )
    count = 0
    for dev_id, client_id, hostname, failing_patches in cur.fetchall():
        # Cap at 20 KBs in the finding details.
        top_kbs = (failing_patches or [])[:20]
        count += _upsert(
            cur, tenant_id, ft_id, client_id, dev_id, "device",
            "patch_failing_repeatedly", "", "high", now,
            {"hostname": hostname, "failing_patches": top_kbs},
            keys,
        )
    return count


def _emit_approval_backlog(cur, tenant_id, ft_ids, now, keys) -> int:
    """Per-client: how many APPROVED patches are not yet installed
    across the client's IN-SCOPE devices?
    """
    ft_id = ft_ids.get("patch_approval_backlog")
    if not ft_id:
        return 0
    cur.execute(
        f"""
        WITH included AS (
            SELECT dl.tenant_id, dl.device_id AS ops_device_id,
                   dl.external_id::int AS ninja_id,
                   v.client_id
            FROM operations.v_device v
            JOIN operations.device_links dl
              ON dl.device_id = v.device_id AND dl.tenant_id = v.tenant_id
            JOIN operations.sources s
              ON s.id = dl.source_id AND s.name = 'Ninja'
            WHERE v.tenant_id = %s
              AND v.effective_patching_scope = 'Included'
              AND v.lifecycle_status <> 'retired'
        ),
        approved_latest AS (
            SELECT DISTINCT ON (pf.device_id, pf.patch_uid)
                pf.device_id, pf.patch_uid, pf.status
            FROM ninja_patches.patch_facts pf
            JOIN included i ON i.ninja_id = pf.device_id
            ORDER BY pf.device_id, pf.patch_uid, pf.last_observed_at DESC
        )
        SELECT i.client_id, c.display_name, COUNT(*) AS backlog
        FROM approved_latest a
        JOIN included i ON i.ninja_id = a.device_id
        JOIN operations.clients c
          ON c.id = i.client_id AND c.deleted_at IS NULL
        WHERE a.status = 'APPROVED'
        GROUP BY i.client_id, c.display_name
        HAVING COUNT(*) >= {_APPROVAL_BACKLOG_THRESHOLD}
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
