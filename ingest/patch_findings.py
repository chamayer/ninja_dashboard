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
    older than 3 days (last_boot_at from generic Ninja detail evidence via
    device_session_current).
  * `patch_failing_repeatedly` — same KB has failed >=3 times on a
    device that is in scope.
  * `patch_approval_backlog` — subject = client; >=25 APPROVED
    uninstalled patches across the client's in-scope devices.

Multi-Ninja-link ops devices are collapsed via aggregation before
emission (BOOL_OR / MAX / SUM) — same E.3 gotcha handled in O1/O3/O4.
"""

from __future__ import annotations

import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone

from ingest import db
from ingest.conditions import record_assessment
from ingest.condition_evidence import (
    device_identity_signal,
    offline_readiness,
    preserve_operator_episode,
)
from shared.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Readiness,
    Signal,
)

log = logging.getLogger(__name__)

_TENANT_ID = 1
_POLICY_DEFAULTS = {
    "patch_activity_days": 35,
    "reboot_pending_days": 3,
    "repeated_failure_count": 3,
    "approval_backlog_count": 25,
}


def _policy(cur, tenant_id: int) -> dict[str, int]:
    """Read the tenant policy written by Operations; retain safe defaults."""
    cur.execute(
        """
        SELECT config FROM operations.evaluator_config
        WHERE tenant_id = %s AND evaluator_name = 'device_status'
        """,
        (tenant_id,),
    )
    row = cur.fetchone()
    stored = row[0] if row and isinstance(row[0], dict) else {}
    policy = dict(_POLICY_DEFAULTS)
    for key, default in _POLICY_DEFAULTS.items():
        try:
            policy[key] = max(1, int(stored.get(key, default)))
        except (TypeError, ValueError):
            policy[key] = default
    return policy


def classify(tenant_id: int = _TENANT_ID) -> int:
    now = datetime.now(timezone.utc)
    error: str | None = None
    affected = 0
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
            ft_ids = _finding_type_ids(cur)
            policy = _policy(cur, tenant_id)

            emitted_keys: set[str] = set()

            affected += _emit_never_patched(cur, tenant_id, ft_ids, now, emitted_keys)
            affected += _emit_patching_stalled(cur, tenant_id, ft_ids, now, emitted_keys, policy)
            affected += _emit_reboot_pending(cur, tenant_id, ft_ids, now, emitted_keys, policy)
            affected += _emit_failing_repeatedly(cur, tenant_id, ft_ids, now, emitted_keys, policy)
            affected += _emit_approval_backlog(cur, tenant_id, ft_ids, now, emitted_keys, policy)

            _auto_resolve(cur, tenant_id, emitted_keys, now, policy)
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
        FROM operations.v_device_source_link dl
        JOIN operations.sources s
          ON s.id = dl.source_id AND s.name = 'Ninja'
        LEFT JOIN ninja_patches.device_patch_signal dps
          ON dps.device_id = dl.external_id::int
        WHERE dl.tenant_id = %s
          AND EXISTS (
              SELECT 1
                FROM operations.device_agent_presence_current ninja_presence
               WHERE ninja_presence.tenant_id = dl.tenant_id
                 AND ninja_presence.device_id = dl.device_id
                 AND ninja_presence.platform = 'Ninja'
                 AND ninja_presence.reported_online IS TRUE
          )
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
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            "device",
            "device_never_patched",
            "",
            "high",
            now,
            {"hostname": hostname, "reason": "no INSTALLED patches on record"},
            keys,
        )
    return count


def _emit_patching_stalled(cur, tenant_id, ft_ids, now, keys, policy) -> int:
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
               OR pd.max_last_seen_at < NOW() - INTERVAL '{policy['patch_activity_days']} days')
        """,
        (tenant_id, tenant_id),
    )
    count = 0
    for dev_id, client_id, hostname, last_seen in cur.fetchall():
        count += _upsert(
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            "device",
            "patching_stalled",
            "",
            "medium",
            now,
            {
                "hostname": hostname,
                "last_patch_seen_at": last_seen.isoformat() if last_seen else None,
                "threshold_days": policy["patch_activity_days"],
            },
            keys,
        )
    return count


def _emit_reboot_pending(cur, tenant_id, ft_ids, now, keys, policy) -> int:
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
          AND EXISTS (
              SELECT 1
                FROM operations.device_agent_presence_current ninja_presence
               WHERE ninja_presence.tenant_id = v.tenant_id
                 AND ninja_presence.device_id = v.device_id
                 AND ninja_presence.platform = 'Ninja'
                 AND ninja_presence.reported_online IS TRUE
          )
          AND (v.last_boot_at IS NULL
               OR v.last_boot_at < NOW() - INTERVAL '{policy['reboot_pending_days']} days')
        """,
        (tenant_id,),
    )
    count = 0
    for dev_id, client_id, hostname, last_boot in cur.fetchall():
        count += _upsert(
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            "device",
            "reboot_pending",
            "",
            "medium",
            now,
            {
                "hostname": hostname,
                "last_boot_at": last_boot.isoformat() if last_boot else None,
                "threshold_days": policy["reboot_pending_days"],
            },
            keys,
        )
    return count


def _emit_failing_repeatedly(cur, tenant_id, ft_ids, now, keys, policy) -> int:
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
            JOIN operations.v_device_source_link dl
              ON dl.device_id = v.device_id AND dl.tenant_id = v.tenant_id
            JOIN operations.sources s
              ON s.id = dl.source_id AND s.name = 'Ninja'
            WHERE v.tenant_id = %s
              AND v.effective_patching_scope = 'Included'
              AND v.lifecycle_status <> 'retired'
              AND EXISTS (
                  SELECT 1
                    FROM operations.device_agent_presence_current ninja_presence
                   WHERE ninja_presence.tenant_id = v.tenant_id
                     AND ninja_presence.device_id = v.device_id
                     AND ninja_presence.platform = 'Ninja'
                     AND ninja_presence.reported_online IS TRUE
              )
        ),
        failing AS (
            SELECT i.ops_device_id, i.client_id, i.canonical_hostname,
                   pf.kb_number, COUNT(*) AS fails
            FROM ninja_patches.patch_facts pf
            JOIN included i ON i.ninja_id = pf.device_id
            WHERE pf.status = 'FAILED' AND pf.kb_number IS NOT NULL
            GROUP BY i.ops_device_id, i.client_id, i.canonical_hostname, pf.kb_number
            HAVING COUNT(*) >= {policy['repeated_failure_count']}
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
            cur,
            tenant_id,
            ft_id,
            client_id,
            dev_id,
            "device",
            "patch_failing_repeatedly",
            "",
            "high",
            now,
            {"hostname": hostname, "failing_patches": top_kbs},
            keys,
        )
    return count


def _emit_approval_backlog(cur, tenant_id, ft_ids, now, keys, policy) -> int:
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
            JOIN operations.v_device_source_link dl
              ON dl.device_id = v.device_id AND dl.tenant_id = v.tenant_id
            JOIN operations.sources s
              ON s.id = dl.source_id AND s.name = 'Ninja'
            WHERE v.tenant_id = %s
              AND v.effective_patching_scope = 'Included'
              AND v.lifecycle_status <> 'retired'
              AND EXISTS (
                  SELECT 1
                    FROM operations.device_agent_presence_current ninja_presence
                   WHERE ninja_presence.tenant_id = v.tenant_id
                     AND ninja_presence.device_id = v.device_id
                     AND ninja_presence.platform = 'Ninja'
                     AND ninja_presence.reported_online IS TRUE
              )
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
        HAVING COUNT(*) >= {policy['approval_backlog_count']}
        """,
        (tenant_id,),
    )
    count = 0
    for client_id, display_name, backlog in cur.fetchall():
        count += _upsert(
            cur,
            tenant_id,
            ft_id,
            client_id,
            client_id,
            "client",
            "patch_approval_backlog",
            "",
            "medium",
            now,
            {"client_name": display_name, "backlog_count": backlog},
            keys,
        )
    return count


def _condition_key(tenant_id, client_id, subject_id, ft_name: str, extra: str) -> str:
    raw = f"{tenant_id}:{client_id}:{subject_id}:{ft_name}:{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _upsert(
    cur,
    tenant_id,
    ft_id,
    client_id,
    subject_id,
    subject_type,
    ft_name,
    extra_key,
    severity,
    now,
    details,
    emitted_keys,
) -> int:
    ckey = _condition_key(tenant_id, client_id, subject_id, ft_name, extra_key)
    if ckey in emitted_keys:
        return 0
    emitted_keys.add(ckey)
    preserved = preserve_operator_episode(cur, "findings", tenant_id, ckey, now, details)
    if preserved is not None:
        _record_assessment(cur, tenant_id, uuid.UUID(preserved), ft_id, ckey, ft_name,
                           subject_type, subject_id, now)
        return 1
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
            WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            last_seen_at     = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            finding_details  = EXCLUDED.finding_details,
            status           = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        RETURNING id
        """,
        (
            tenant_id,
            ft_id,
            client_id,
            subject_type,
            subject_id,
            json.dumps(details),
            ckey,
            severity,
            now,
            now,
            now,
        ),
    )
    finding_id = cur.fetchone()[0]
    _record_assessment(cur, tenant_id, finding_id, ft_id, ckey, ft_name,
                       subject_type, subject_id, now)
    return 1


def _record_assessment(cur, tenant_id, finding_id, ft_id, condition_key,
                       type_name, subject_type, subject_id, now) -> None:
    """Record current patch evidence when the live contract is installed."""
    cur.execute("SELECT to_regclass('operations.condition_assessments') IS NOT NULL")
    if not cur.fetchone()[0]:
        return
    participant = Participant(subject_type, str(subject_id), "affected", tenant_id)
    condition = Condition(
        tenant_id, "entity", str(finding_id), type_name, condition_key, "open",
        (participant,),
    )
    signals = ()
    if subject_type == "device":
        identity = device_identity_signal(cur, tenant_id, str(subject_id))
        cur.execute(
            """
            SELECT COALESCE(last_contact_at, last_observed_at)
              FROM operations.device_agent_presence_current
             WHERE tenant_id = %s AND device_id = %s AND platform = 'Ninja'
             ORDER BY COALESCE(last_contact_at, last_observed_at) DESC NULLS LAST
             LIMIT 1
            """,
            (tenant_id, subject_id),
        )
        contact_row = cur.fetchone()
        offline_state, offline_reason = offline_readiness(
            [contact_row[0] if contact_row else None],
            now=now,
            offline_days=_policy(cur, tenant_id)["patch_activity_days"],
        )
        signals = (
            identity,
            Signal("offline", participant, offline_state, offline_reason),
        )
    record_assessment(
        cur,
        condition,
        signals,
        _patch_evaluation_coverage(cur, tenant_id, subject_type, subject_id),
        now=now,
        reevaluation_key=f"patch:{condition_key}",
        participant=participant,
    )


def _patch_evaluation_coverage(cur, tenant_id, subject_type, subject_id):
    """Measure the source scope used by this patch assessment."""
    if subject_type == "device":
        cur.execute(
            """
            SELECT to_regclass('operations.v_device') IS NOT NULL
               AND to_regclass('operations.device_agent_presence_current') IS NOT NULL
               AND to_regclass('ninja_patches.device_patch_signal') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM operations.v_device
                    WHERE tenant_id = %s AND device_id = %s
               )
            """,
            (tenant_id, subject_id),
        )
    elif subject_type == "client":
        cur.execute(
            """
            SELECT to_regclass('operations.clients') IS NOT NULL
               AND to_regclass('ninja_patches.patch_facts') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM operations.clients
                    WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL
               )
            """,
            (tenant_id, subject_id),
        )
    else:
        cur.execute("SELECT FALSE")
    measured = bool(cur.fetchone()[0])
    return EvaluationCoverage(measured, measured, measured, measured)


def _auto_resolve(cur, tenant_id, emitted_keys, now, policy) -> None:
    """Close findings that no longer meet the active patching criteria.

    A patch condition is actionable only while Ninja currently reports the
    Computer online.  Closing retains the complete finding history while
    removing an offline, stale, or withdrawn source record from the active
    queue until current evidence supports it again.
    """
    # An empty emission can represent a failed, partial, or skipped upstream
    # read. It is not proof that every prior patch finding has cleared.
    if not emitted_keys:
        return
    cur.execute(
        f"""
        UPDATE operations.findings f
        SET status = 'resolved',
            last_seen_at = %s,
            closed_at = COALESCE(f.closed_at, %s),
            finding_details = f.finding_details || jsonb_build_object(
                'resolution', jsonb_build_object(
                    'reason', 'no_longer_actionable',
                    'detail', 'The Computer no longer meets the active patching criteria.'
                )
            )
        FROM operations.finding_types ft
        WHERE ft.id = f.finding_type_id
          AND ft.source_module = 'platform.patch_findings'
          AND f.tenant_id = %s
          AND f.status IN ('open', 'acknowledged')
          AND NOT (f.condition_key = ANY(%s::text[]))
          AND to_regclass('operations.condition_assessments') IS NOT NULL
          AND EXISTS (
               SELECT 1 FROM operations.condition_assessments a
              WHERE a.tenant_id = f.tenant_id AND a.row_kind = 'entity'
                AND a.finding_id = f.id
                AND (a.response->>'may_clear')::boolean IS TRUE
                AND a.policy_version = (
                    SELECT v.version FROM operations.condition_policy_versions v
                    WHERE v.active ORDER BY v.version DESC LIMIT 1
                )
                AND a.assessed_at >= now() - (
                    SELECT (v.policy->>'freshness_hours')::integer
                    FROM operations.condition_policy_versions v
                    WHERE v.active ORDER BY v.version DESC LIMIT 1
                ) * interval '1 hour'
          )
          AND EXISTS (
              SELECT 1
                FROM operations.v_device v
                JOIN operations.v_device_source_link link
                  ON link.tenant_id = v.tenant_id AND link.device_id = v.device_id
                JOIN operations.sources source
                  ON source.id = link.source_id AND source.name = 'Ninja'
                JOIN operations.device_agent_presence_current presence
                  ON presence.tenant_id = v.tenant_id
                 AND presence.device_id = v.device_id
                 AND presence.platform = 'Ninja'
                 AND presence.reported_online IS TRUE
               WHERE f.subject_type = 'device'
                 AND f.subject_id = v.device_id
                 AND v.tenant_id = f.tenant_id
                 AND v.effective_patching_scope = 'Included'
                 AND v.lifecycle_status <> 'retired'
                 AND (
                     (ft.name = 'device_never_patched' AND EXISTS (
                         SELECT 1 FROM ninja_patches.device_patch_signal signal
                          WHERE signal.device_id = link.external_id::int
                            AND signal.ever_installed IS TRUE
                     ))
                     OR (ft.name = 'patching_stalled' AND EXISTS (
                         SELECT 1 FROM ninja_patches.device_patch_signal signal
                          WHERE signal.device_id = link.external_id::int
                            AND signal.last_seen_at >= now() - interval '{policy['patch_activity_days']} days'
                     ))
                     OR (ft.name = 'reboot_pending' AND (
                         v.needs_reboot IS FALSE
                         OR v.last_boot_at >= now() - interval '{policy['reboot_pending_days']} days'
                     ))
                     OR (ft.name = 'patch_failing_repeatedly' AND NOT EXISTS (
                         SELECT 1 FROM ninja_patches.patch_facts facts
                          WHERE facts.device_id = link.external_id::int
                            AND facts.status = 'FAILED'
                            AND facts.kb_number IS NOT NULL
                          GROUP BY facts.kb_number
                         HAVING COUNT(*) >= {policy['repeated_failure_count']}
                     ))
                 )
          )
          AND NOT EXISTS (
              SELECT 1 FROM operations.condition_participants p
              WHERE p.tenant_id = f.tenant_id AND p.row_kind = 'entity'
                AND p.finding_id = f.id AND p.participant_role <> 'context'
                AND NOT EXISTS (
                    SELECT 1 FROM operations.condition_assessments pa
                    WHERE pa.tenant_id = p.tenant_id AND pa.row_kind = p.row_kind
                      AND pa.finding_id = p.finding_id
                      AND pa.participant_kind = p.participant_kind
                      AND pa.participant_id = p.participant_id
                      AND pa.participant_role = p.participant_role
                      AND (pa.response->>'may_clear')::boolean IS TRUE
                      AND pa.policy_version = (
                          SELECT v.version FROM operations.condition_policy_versions v
                          WHERE v.active ORDER BY v.version DESC LIMIT 1
                      )
                      AND pa.assessed_at >= now() - (
                          SELECT (v.policy->>'freshness_hours')::integer
                          FROM operations.condition_policy_versions v
                          WHERE v.active ORDER BY v.version DESC LIMIT 1
                      ) * interval '1 hour'
                )
          )
        """,
        (now, now, tenant_id, list(emitted_keys) if emitted_keys else [""]),
    )
