"""Platform evaluator.

Reads coverage_requirements and entity_observations to generate and update
entity findings in operations.findings. Runs after each ingest cycle and
on a 4-hour sweep.

Pipeline per run (device_id=None means full sweep):
  1. Source-failure guard — platforms whose latest run_log entry failed
     or is overdue are skipped for coverage this cycle and raise an
     admin_findings row (resolved automatically once healthy).
  2. Device-role sync — devices get their server/workstation role from
     the latest role-bearing observation of any source; disagreeing
     sources raise device_role_conflict (Ninja stays authoritative).
  3. Coverage — missing_required_platform (never observed) and
     stale_required_platform (observed before, quiet past the gap
     threshold). Requirements filter on device_scope and skip exempted
     entity_types. Confidence is capped at 'probable' unless another
     source saw the device online recently (corroboration).
  4. Lifecycle — device_missing_from_source, device_offline,
     device_stale_data. (cross_client_conflict removed 2026-07-14 —
     see BLUEPRINT §1.7.)
  5. Auto-resolve for all of the above once conditions clear.

All operations.* access runs under SET LOCAL operations.tenant_id so RLS
is satisfied. Severity is immutable once set; only confidence and
last_detected_at are updated on repeat detections.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ingest import db
from ingest.normalize import normalize_hostname

log = logging.getLogger(__name__)

_DEVICE_MISSING_MIN_AGE_HOURS = 1
_SOURCE_OVERDUE_HOURS = 24
_CORROBORATION_WINDOW_HOURS = 48
_LONG_OFFLINE_DAYS = 7
_STALE_DATA_DAYS = 7


def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int:
    """Evaluate coverage gaps and lifecycle events for a tenant.

    Returns the number of findings opened or updated. Writes a
    `platform_evaluator` row to operations.run_log so operators can see
    when the evaluator ran and how many findings the run touched.
    """
    now = datetime.now(timezone.utc)
    affected = 0
    error_msg: str | None = None
    skip_platforms: set[str] = set()

    try:
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL operations.tenant_id = {tenant_id}")
                skip_platforms = _source_failure_guard(cur, tenant_id, now)
                if device_id is None:
                    affected += _sync_device_roles(cur, tenant_id, now)
                    _sync_lifecycle_status(cur, tenant_id)
                    affected += _evaluate_unknown_entities(cur, tenant_id, now)
                    affected += _evaluate_duplicate_records(cur, tenant_id, now)
                corroborated = _load_corroborated_devices(cur, tenant_id)
                affected += _evaluate_coverage(
                    cur, tenant_id, device_id, now, skip_platforms, corroborated
                )
                affected += _evaluate_unenrolled(cur, tenant_id, device_id, now)
                affected += _evaluate_device_lifecycle(cur, tenant_id, device_id, now)
                # cross_client_conflict emitter removed 2026-07-14 — see
                # BLUEPRINT §1.7 for design rationale. Existing findings
                # closed in migration 0034.
                affected += _auto_resolve(cur, tenant_id, device_id, now)
    except Exception as exc:
        error_msg = str(exc)[:2000]
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
                    VALUES (gen_random_uuid(), %s, 'platform_evaluator',
                            %s::jsonb, %s, NOW(), %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        json.dumps({"device_id": str(device_id) if device_id else None}),
                        now,
                        error_msg is None,
                        affected,
                        error_msg or "",
                    ),
                )
        except Exception:
            log.exception("evaluator: run_log write failed — continuing")

    log.info(
        "evaluator: tenant=%d findings_affected=%d skipped_platforms=%s",
        tenant_id, affected, sorted(skip_platforms) or "-",
    )
    return affected


# --------------------------------------------------------------------------
# 1. Source-failure guard
# --------------------------------------------------------------------------

def _source_failure_guard(cur: Any, tenant_id: int, now: datetime) -> set[str]:
    """Return platforms to skip this cycle; maintain source_failure admin findings.

    A platform is skipped when its latest run_log entry failed, or its
    latest success is older than _SOURCE_OVERDUE_HOURS. Platforms with no
    run_log rows at all are treated as healthy (transition period — the
    writers only started recording runs with this release).
    """
    cur.execute(
        """
        SELECT DISTINCT platform FROM operations.coverage_requirements
        WHERE tenant_id = %s AND enabled = TRUE
        """,
        (tenant_id,),
    )
    platforms = [row[0] for row in cur.fetchall()]

    ft_id = _get_finding_type_id(cur, "source_failure")
    skip: set[str] = set()
    for platform in platforms:
        cur.execute(
            """
            SELECT ok, ended_at, error FROM operations.run_log
            WHERE tenant_id = %s
              AND (kind = %s OR kind LIKE %s)
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (tenant_id, f"source.{platform}", f"source.{platform}.%"),
        )
        row = cur.fetchone()
        if row is None:
            continue
        ok, ended_at, error = row
        reason = ""
        if not ok:
            reason = f"latest run failed: {error or 'unknown error'}"
        elif ended_at is not None:
            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(tzinfo=timezone.utc)
            if now - ended_at > timedelta(hours=_SOURCE_OVERDUE_HOURS):
                reason = f"no successful run since {ended_at.isoformat()}"

        condition_key = f"source_failure:{platform}"
        if reason:
            skip.add(platform)
            if ft_id:
                severity = "critical" if platform == "Ninja" else "high"
                _upsert_admin_finding(
                    cur, tenant_id, ft_id, condition_key, severity, now,
                    {"platform": platform},
                    {"reason": reason[:500]},
                )
        else:
            cur.execute(
                """
                UPDATE operations.admin_findings
                SET status = 'resolved', resolved_at = %s
                WHERE tenant_id = %s AND condition_key = %s
                  AND status IN ('open', 'acknowledged')
                """,
                (now, tenant_id, condition_key),
            )

    return skip


def _upsert_admin_finding(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    condition_key: str,
    severity: str,
    now: datetime,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
) -> None:
    cur.execute(
        """
        INSERT INTO operations.admin_findings (
            id, version, tenant_id, finding_type_id, condition_key, severity,
            status, subject_ref, details, first_detected_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s, %s, 'open', %s::jsonb, %s::jsonb, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE status IN ('open', 'acknowledged')
        DO UPDATE SET
            last_detected_at = EXCLUDED.last_detected_at,
            details          = EXCLUDED.details
        """,
        (
            tenant_id, finding_type_id, condition_key, severity,
            json.dumps(subject_ref), json.dumps(details), now, now,
        ),
    )


# --------------------------------------------------------------------------
# 2. Device-role sync (any source, never guessed)
# --------------------------------------------------------------------------

def _sync_device_roles(cur: Any, tenant_id: int, now: datetime) -> int:
    """Set device_role from any source's explicit signal; flag disagreements.

    Ninja stays authoritative when sources disagree (the Ninja pull
    already synced its own signal in ingest.core.devices); this fills in
    devices Ninja gave no signal for and raises device_role_conflict
    when sources' latest claims differ.
    """
    cur.execute(
        """
        SELECT DISTINCT ON (device_id, platform)
               device_id, platform,
               COALESCE(canonical_data ->> 'device_role',
                        canonical_data ->> 'device_type') AS device_role
        FROM operations.entity_observation_current
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND active = TRUE
          AND COALESCE(canonical_data ->> 'device_role',
                       canonical_data ->> 'device_type') IS NOT NULL
          AND observed_at > now() - INTERVAL '7 days'
        ORDER BY device_id, platform, observed_at DESC
        """,
        (tenant_id,),
    )
    claims: dict[uuid.UUID, dict[str, str]] = {}
    for dev_id, platform, role in cur.fetchall():
        claims.setdefault(dev_id, {})[platform] = role

    if not claims:
        return 0

    cur.execute(
        """
        SELECT id, client_id, canonical_hostname, device_role
        FROM operations.devices
        WHERE tenant_id = %s AND deleted_at IS NULL AND id = ANY(%s)
        """,
        (tenant_id, list(claims)),
    )
    devices = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    ft_id = _get_finding_type_id(cur, "device_role_conflict")
    count = 0
    conflict_ids: list[uuid.UUID] = []
    for dev_id, dev_claims in claims.items():
        info = devices.get(dev_id)
        if info is None:
            continue
        client_id, hostname, current_role = info
        distinct = set(dev_claims.values())
        target = dev_claims.get("Ninja") or (
            next(iter(distinct)) if len(distinct) == 1 else None
        )
        if target and target != current_role:
            cur.execute(
                "UPDATE operations.devices SET device_role = %s WHERE id = %s",
                (target, dev_id),
            )
        if len(distinct) > 1:
            conflict_ids.append(dev_id)
            if ft_id:
                ckey = _condition_key(
                    tenant_id, client_id, dev_id, "device_role_conflict", ""
                )
                count += _upsert_finding(
                    cur, tenant_id, ft_id, client_id, dev_id,
                    ckey, "low", "confirmed", now,
                    {"hostname": hostname, "claims": dev_claims},
                )

    if ft_id:
        _resolve_findings_absent(cur, tenant_id, ft_id, conflict_ids, now)
    return count


# --------------------------------------------------------------------------
# 2b. Lifecycle status sync (platform truth from device_agent_presence_current)
# --------------------------------------------------------------------------

def _sync_lifecycle_status(cur: Any, tenant_id: int) -> None:
    """Advance/reset lifecycle_status from last platform contact.

    active <7d, offline_aging 7-30d, pending_cleanup >30d, measured from
    the newest last_contact_at across all entity streams (falling back to
    fetch time where the source carries no contact clock). 'retired' is an
    operator decision — never touched here.
    """
    cur.execute(
        """
        WITH contact AS (
            SELECT device_id,
                   MAX(COALESCE(last_contact_at, last_observed_at)) AS last_contact
            FROM operations.device_agent_presence_current
            WHERE tenant_id = %s
            GROUP BY device_id
        ), target AS (
            SELECT device_id,
                   CASE
                       WHEN last_contact < now() - INTERVAL '30 days' THEN 'pending_cleanup'
                       WHEN last_contact < now() - INTERVAL '7 days'  THEN 'offline_aging'
                       ELSE 'active'
                   END AS status
            FROM contact
        )
        UPDATE operations.devices d
        SET lifecycle_status = t.status
        FROM target t
        WHERE d.id = t.device_id
          AND d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND d.lifecycle_status <> 'retired'
          AND d.lifecycle_status <> t.status
        """,
        (tenant_id, tenant_id),
    )
    if cur.rowcount:
        log.info("lifecycle sync: %d devices transitioned", cur.rowcount)


# --------------------------------------------------------------------------
# 2c. Unmapped node_class surveillance (nothing dropped silently)
# --------------------------------------------------------------------------

def _evaluate_unknown_entities(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per Ninja node_class that has no entity_type mapping."""
    ft_id = _get_finding_type_id(cur, "unmapped_node_class")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT COALESCE(canonical_data ->> 'node_class', '(none)'),
               COUNT(*)::int
        FROM operations.entity_observations
        WHERE tenant_id = %s AND entity_type = 'unknown'
          AND observed_at > now() - INTERVAL '2 days'
        GROUP BY 1
        """,
        (tenant_id,),
    )
    rows = cur.fetchall()
    count = 0
    present_keys: list[str] = []
    for node_class, n in rows:
        ckey = f"unmapped_node_class:{node_class}"
        present_keys.append(ckey)
        _upsert_admin_finding(
            cur, tenant_id, ft_id, ckey, "medium", now,
            {"node_class": node_class},
            {"recent_observations": n},
        )
        count += 1
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = %s
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return count


# --------------------------------------------------------------------------
# 2d. Same-stream hostname duplicates (license-consuming rows, never merged)
# --------------------------------------------------------------------------

def _evaluate_duplicate_records(cur: Any, tenant_id: int, now: datetime) -> int:
    """Admin finding per (client, platform, stream, hostname) with >1 records.

    Identity keeps these as separate device rows (hostname correlation is
    cross-source only); this surfaces each duplicate group for cleanup since
    every extra platform record consumes a license.
    """
    ft_id = _get_finding_type_id(cur, "duplicate_platform_record")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT DISTINCT ON (platform, entity_type, entity_key)
               platform, entity_type, entity_key, client_id,
               canonical_data ->> 'hostname',
               canonical_data ->> 'is_online',
               canonical_data ->> 'last_seen_at',
               canonical_data ->> 'serial_number'
        FROM operations.entity_observations
        WHERE tenant_id = %s AND entity_type <> 'software'
          AND observed_at > now() - INTERVAL '2 days'
        ORDER BY platform, entity_type, entity_key, observed_at DESC
        """,
        (tenant_id,),
    )
    groups: dict[tuple, list[dict]] = {}
    for (platform, entity_type, entity_key, client_id, hostname,
         is_online, last_seen, serial) in cur.fetchall():
        norm = normalize_hostname(hostname)
        if not norm:
            continue
        groups.setdefault(
            (platform, entity_type, str(client_id or ""), norm), []
        ).append({
            "entity_key": entity_key,
            "is_online": is_online,
            "last_seen_at": last_seen,
            "serial_number": serial,
        })

    count = 0
    present_keys: list[str] = []
    for (platform, entity_type, client_key, norm), records in groups.items():
        if len(records) < 2:
            continue
        ckey = f"duplicate_record:{platform}:{entity_type}:{client_key}:{norm}"
        present_keys.append(ckey)
        severity = "high" if entity_type.startswith("agent.") else "low"
        records.sort(key=lambda r: r["last_seen_at"] or "", reverse=True)
        _upsert_admin_finding(
            cur, tenant_id, ft_id, ckey, severity, now,
            {"platform": platform, "entity_type": entity_type,
             "hostname": norm, "client_id": client_key or None},
            {"record_count": len(records),
             "entity_keys": [r["entity_key"] for r in records],
             "records": records,
             "offline_count": sum(
                 1 for r in records if r["is_online"] in ("false", "False")
             )},
        )
        count += 1
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = %s
        WHERE tenant_id = %s AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (condition_key = ANY(%s))
        """,
        (now, tenant_id, ft_id, present_keys),
    )
    return count


# --------------------------------------------------------------------------
# 3. Coverage
# --------------------------------------------------------------------------

def _load_corroborated_devices(cur: Any, tenant_id: int) -> set[uuid.UUID]:
    """Devices some source saw online recently — allows 'confirmed' gaps."""
    cur.execute(
        """
        SELECT DISTINCT device_id
        FROM operations.entity_observations
        WHERE tenant_id = %s AND device_id IS NOT NULL
          AND observed_at > now() - %s::interval
          AND canonical_data ->> 'is_online' = 'true'
        """,
        (tenant_id, f"{_CORROBORATION_WINDOW_HOURS} hours"),
    )
    return {row[0] for row in cur.fetchall()}


def _evaluate_coverage(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
    skip_platforms: set[str],
    corroborated: set[uuid.UUID],
) -> int:
    """Emit missing_/stale_required_platform findings per tiered lookup.

    Requirement resolution is profile-first (BLUEPRINT C.6):

        1. If Client.requirement_profile IS NOT NULL → use profile.items,
           tier order (profile, device_role) → (profile, "all"). Empty
           profile = "nothing required," no fall-through to global.
        2. Else → fall through to global coverage_requirements
           (client_id IS NULL), tier order (None, device_role) →
           (None, "all").

    A profile-bound client with ONE (all) item saying "Ninja only" gets
    Ninja evaluated and nothing else — S1/LMI globals do not apply.
    A profile-bound client with ZERO items (e.g. A.M.Rose) fires no
    coverage findings at all.
    """
    # Agent reference: id → (name, entity_type, supported_os_groups)
    cur.execute(
        """
        SELECT id, name, entity_type, supported_os_groups
        FROM operations.agents
        """
    )
    agents_by_id: dict[int, tuple] = {
        row[0]: (row[1], row[2], row[3] or []) for row in cur.fetchall()
    }

    # Global rows (fallback for clients without a profile). Tuple shape:
    #   (id, client_id, agent_id, entity_type, platform, scope, applicable_os_groups,
    #    severity, gap, prob, conf)
    cur.execute(
        """
        SELECT id, client_id, agent_id, entity_type, platform, device_scope,
               applicable_os_groups,
               severity, gap_after_hours, confidence_probable, confidence_confirmed
        FROM operations.coverage_requirements
        WHERE tenant_id = %s AND enabled = TRUE AND client_id IS NULL
        """,
        (tenant_id,),
    )
    global_rows = cur.fetchall()

    # Profile-based tiers.
    cur.execute(
        """
        SELECT rpi.profile_id, NULL::uuid AS id, NULL AS client_id,
               rpi.agent_id, rpi.entity_type, rpi.platform, rpi.device_scope,
               rpi.applicable_os_groups,
               rpi.severity, rpi.gap_after_hours,
               rpi.confidence_probable, rpi.confidence_confirmed
        FROM operations.requirement_profile_items rpi
        WHERE rpi.tenant_id = %s
        """,
        (tenant_id,),
    )
    profile_rows = cur.fetchall()

    # profile_id → scope → list of item tuples
    profile_tiers: dict[Any, dict[str, list[tuple]]] = {}
    for pid, _id, _cid, agent_id, entity_type, platform, scope, aog, *rest in profile_rows:
        profile_tiers.setdefault(pid, {}).setdefault(scope, []).append(
            (None, None, agent_id, entity_type, platform, scope, aog, *rest)
        )

    global_tiers: dict[str, list[tuple]] = {}
    for row in global_rows:
        scope = row[5]
        global_tiers.setdefault(scope, []).append(row)

    # client_id → profile_id
    cur.execute(
        """
        SELECT id, requirement_profile_id
        FROM operations.clients
        WHERE tenant_id = %s AND deleted_at IS NULL
        """,
        (tenant_id,),
    )
    client_profile: dict[Any, Any] = {row[0]: row[1] for row in cur.fetchall()}

    if not global_rows and not profile_rows:
        return 0

    def resolve_tier(dev_client_id, dev_role: str) -> list[tuple]:
        profile_id = client_profile.get(dev_client_id)
        if profile_id is not None:
            scopes = profile_tiers.get(profile_id, {})
            # Profile-bound: use profile items only. Empty profile → [].
            for scope_key in (dev_role, "all"):
                rows = scopes.get(scope_key)
                if rows:
                    return rows
            return []
        # No profile → global fallback.
        for scope_key in (dev_role, "all"):
            rows = global_tiers.get(scope_key)
            if rows:
                return rows
        return []

    missing_ft = _get_finding_type_id(cur, "missing_required_platform")
    stale_ft = _get_finding_type_id(cur, "stale_required_platform")
    if missing_ft is None:
        log.warning("evaluator: finding_type 'missing_required_platform' not found")
        return 0

    # Pre-compute devices that are fully offline (last contact across
    # ALL agents older than the device_offline threshold). Per
    # BLUEPRINT §1.8, `stale_required_platform` should NOT fire on
    # such devices — the device-level `device_offline` finding covers
    # them, and per-agent stale is redundant noise when the whole
    # device is silent. `missing_required_platform` STILL fires on
    # offline devices (the agent was never installed, that's a real
    # gap regardless of current online state).
    cur.execute(
        f"""
        SELECT apc.device_id
        FROM operations.device_agent_presence_current apc
        WHERE apc.tenant_id = %s
          AND apc.entity_type LIKE 'agent.%%'
        GROUP BY apc.device_id
        HAVING MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
             < NOW() - INTERVAL '{_LONG_OFFLINE_DAYS} days'
        """,
        (tenant_id,),
    )
    fully_offline_devices = {r[0] for r in cur.fetchall()}

    # Pull every device + agent-universe flag once. Exemptions come from
    # device_operator_decisions (Track O batch O3 — polymorphic operator
    # decisions storage). Empty {} if no row.
    cur.execute(
        """
        SELECT d.id, d.client_id, d.canonical_hostname, d.device_role,
               COALESCE(op.value, '{}'::jsonb) AS exemptions,
               d.os_group,
               EXISTS(SELECT 1 FROM operations.device_agent_presence_current apc
                      WHERE apc.tenant_id = d.tenant_id AND apc.device_id = d.id
                        AND apc.entity_type LIKE 'agent.%%') AS in_agent_universe
        FROM operations.devices d
        LEFT JOIN operations.device_operator_decisions op
          ON op.tenant_id = d.tenant_id
         AND op.device_id = d.id
         AND op.dimension = 'exemptions'
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND d.lifecycle_status != 'retired'
          AND (%s::uuid IS NULL OR d.id = %s)
        """,
        (tenant_id, device_id, device_id),
    )
    devices = cur.fetchall()

    count = 0
    for dev_id, dev_client_id, hostname, dev_role, exemptions, os_group, in_universe in devices:
        exemptions = exemptions or {}
        # BLUEPRINT E.6: coverage evaluates against entity types. A device
        # with zero agent.* observations is not in the coverage universe —
        # it's a hypervisor / NMS tracking record. Skipped here; picked up
        # by _evaluate_unenrolled instead.
        if not in_universe:
            continue
        tier_rows = resolve_tier(dev_client_id, dev_role or "all")
        for (_rid, _rclient, agent_id, entity_type, platform, _rscope, aog,
             severity, gap_hours, prob_hours, conf_hours) in tier_rows:
            if platform in skip_platforms:
                continue
            if entity_type in exemptions:
                continue
            # Agent physics: skip if device's os_group isn't in the
            # supported set (LMI on Linux etc). applicable_os_groups on
            # the item narrows further if set; else falls to the Agent's
            # supported_os_groups.
            allowed_groups = None
            if aog:
                allowed_groups = set(aog)
            elif agent_id and agent_id in agents_by_id:
                allowed_groups = set(agents_by_id[agent_id][2])
            if allowed_groups is not None and os_group not in allowed_groups:
                continue

            # Per-device presence for this (entity_type, platform), 'any'
            # honored (BLUEPRINT C.6 wildcard).
            # BLUEPRINT E.6: staleness uses platform LAST CONTACT, not our
            # fetch time. `last_observed_at` is when WE polled the source
            # API — always recent; `last_contact_at` is when the source
            # last heard from the DEVICE. Fall back only when contact is
            # unpopulated (some sources don't distinguish).
            cur.execute(
                """
                SELECT MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
                FROM operations.device_agent_presence_current apc
                WHERE apc.tenant_id = %s AND apc.device_id = %s
                  AND apc.entity_type = %s
                  AND (%s = 'any' OR apc.platform = %s)
                """,
                (tenant_id, dev_id, entity_type, platform, platform),
            )
            (last_observed,) = cur.fetchone()

            # BLUEPRINT 1.4 split:
            #   MISSING (last_observed IS NULL) → emit immediately.
            #   STALE (present but past gap_hours) → confidence ladder.
            offline_downgrade = dev_id in fully_offline_devices
            if last_observed is None:
                confidence = "confirmed" if dev_id in corroborated else "probable"
                ftype, ft_name, sev = missing_ft, "missing_required_platform", severity
            else:
                if last_observed.tzinfo is None:
                    last_observed = last_observed.replace(tzinfo=timezone.utc)
                gap_age_hours = (now - last_observed).total_seconds() / 3600
                if gap_age_hours < gap_hours:
                    continue
                if gap_age_hours >= conf_hours:
                    confidence = "confirmed"
                elif gap_age_hours >= prob_hours:
                    confidence = "probable"
                else:
                    confidence = "possible"
                if confidence == "confirmed" and dev_id not in corroborated:
                    confidence = "probable"
                if stale_ft is None:
                    continue
                ftype, ft_name, sev = stale_ft, "stale_required_platform", "medium"

            # If the whole device is offline (all agents silent past
            # the device_offline threshold), the device-level
            # `device_offline` finding is the actionable signal. Keep
            # the per-agent missing / stale finding VISIBLE — operators
            # still want to see which agent is missing on an offline
            # device — but demote severity to `info` and mark
            # `finding_details.reason_suppressed='device_offline'` so
            # the queue can filter it out and the label can hint at
            # the offline context. Previously suppressed entirely
            # (BLUEPRINT §1.8 pre-2026-07-21).
            details = {"entity_type": entity_type, "platform": platform, "hostname": hostname}
            if offline_downgrade:
                sev = "info"
                details["reason_suppressed"] = "device_offline"

            ckey = _condition_key(tenant_id, dev_client_id, dev_id, ft_name, platform)
            count += _upsert_finding(
                cur, tenant_id, ftype, dev_client_id, dev_id,
                ckey, sev, confidence, now, details,
            )

    return count


# --------------------------------------------------------------------------
# 3b. Unenrolled devices (outside agent universe)
# --------------------------------------------------------------------------

def _evaluate_unenrolled(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Emit `device_unenrolled` for devices tracked by hypervisor / NMS /
    monitor sources but never observed as an agent target.

    finding_details pulls power_state, hypervisor host, last_boot_time,
    last observation timestamp from the latest vm.guest / vm.host /
    network.device / monitor.target observation, so the operator has
    triage data (running vs powered off, hypervisor host name, when it
    was last seen).
    """
    ft_id = _get_finding_type_id(cur, "device_unenrolled")
    if ft_id is None:
        return 0

    cur.execute(
        """
        WITH latest_tracking AS (
            SELECT DISTINCT ON (eo.device_id)
                   eo.device_id, eo.entity_type, eo.observed_at,
                   eo.canonical_data
            FROM operations.entity_observations eo
            WHERE eo.tenant_id = %s
              AND eo.device_id IS NOT NULL
              AND eo.entity_type IN ('vm.guest', 'vm.host', 'network.device',
                                     'monitor.target')
            ORDER BY eo.device_id, eo.observed_at DESC
        )
        SELECT d.id, d.client_id, d.canonical_hostname, d.device_type,
               lt.entity_type, lt.observed_at, lt.canonical_data
        FROM operations.devices d
        JOIN latest_tracking lt ON lt.device_id = d.id
        WHERE d.tenant_id = %s
          AND d.deleted_at IS NULL
          AND d.lifecycle_status != 'retired'
          AND (%s::uuid IS NULL OR d.id = %s)
          AND NOT EXISTS(
              SELECT 1 FROM operations.device_agent_presence_current apc
              WHERE apc.tenant_id = d.tenant_id AND apc.device_id = d.id
                AND apc.entity_type LIKE 'agent.%%'
          )
        """,
        (tenant_id, tenant_id, device_id, device_id),
    )
    unenrolled = cur.fetchall()

    count = 0
    for dev_id, dev_client_id, hostname, device_type, entity_type, obs_at, cd in unenrolled:
        cd = cd or {}
        if obs_at and obs_at.tzinfo is None:
            obs_at = obs_at.replace(tzinfo=timezone.utc)
        days = (
            int((now - obs_at).total_seconds() // 86400) if obs_at else None
        )
        details = {
            "hostname": hostname,
            "device_type": device_type,
            "observed_via": entity_type,
            "power_state": cd.get("power_state"),
            "parent_ninja_id": cd.get("parent_ninja_id"),
            "last_boot_time_at": cd.get("last_boot_time_at"),
            "last_observed_at": obs_at.isoformat() if obs_at else None,
            "days_since_last_seen": days,
        }
        ckey = _condition_key(
            tenant_id, dev_client_id, dev_id, "device_unenrolled", "",
        )
        count += _upsert_finding(
            cur, tenant_id, ft_id, dev_client_id, dev_id,
            ckey, "medium", "confirmed", now, details,
        )
    return count


# --------------------------------------------------------------------------
# 4. Lifecycle
# --------------------------------------------------------------------------

def _evaluate_device_lifecycle(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """device_missing_from_source, device_offline, device_stale_data."""
    count = 0

    missing_type_id = _get_finding_type_id(cur, "device_missing_from_source")
    if missing_type_id:
        threshold = now - timedelta(hours=_DEVICE_MISSING_MIN_AGE_HOURS)
        cur.execute(
            """
            SELECT DISTINCT d.id, d.client_id, d.canonical_hostname
            FROM operations.devices d
            JOIN operations.device_links dl ON dl.device_id = d.id AND dl.tenant_id = d.tenant_id
            JOIN operations.sources s ON s.id = dl.source_id
            WHERE d.tenant_id = %s
              AND d.deleted_at IS NULL
              AND dl.missing_since IS NOT NULL
              AND dl.missing_since <= %s
              AND (%s::uuid IS NULL OR d.id = %s)
            """,
            (tenant_id, threshold, device_id, device_id),
        )
        for dev_id, dev_client_id, hostname in cur.fetchall():
            ckey = _condition_key(tenant_id, dev_client_id, dev_id, "device_missing_from_source", "")
            count += _upsert_finding(
                cur, tenant_id, missing_type_id, dev_client_id, dev_id,
                ckey, "high", "confirmed", now,
                {"hostname": hostname},
            )

    if device_id is None:
        count += _evaluate_device_offline(cur, tenant_id, now)
        count += _evaluate_stale_data(cur, tenant_id, now)
    return count


def _evaluate_device_offline(cur: Any, tenant_id: int, now: datetime) -> int:
    """Device is unreachable via EVERY agent source (BLUEPRINT §1.8).

    Fires when a device has agent presence rows but the most recent
    platform last-contact across ALL agents is older than the threshold
    — i.e., no source is hearing the device.

    This is device-level truth. A device where one agent (say Ninja)
    stopped talking while others (S1/LMI) are still in contact is NOT
    "offline" — it's a per-source staleness case handled by
    `stale_required_platform` with `platform=<source>` in details.
    """
    ft_id = _get_finding_type_id(cur, "device_offline")
    if ft_id is None:
        return 0
    threshold_interval = f"{_LONG_OFFLINE_DAYS} days"
    # Per-platform last-seen is preserved as evidence on the finding
    # so operators triaging a fully-offline device can see the exact
    # timeline ("went dark on Ninja 7/10 → SentinelOne 7/12 →
    # ScreenConnect 7/14 → fully offline since 7/14") without
    # having to click through to the device detail Sources tab.
    cur.execute(
        """
        WITH per_platform AS (
            SELECT tenant_id, device_id, platform,
                   MAX(COALESCE(last_contact_at, last_observed_at)) AS last_seen
            FROM operations.device_agent_presence_current
            WHERE tenant_id = %s
              AND entity_type LIKE 'agent.%%'
            GROUP BY tenant_id, device_id, platform
        )
        SELECT pp.device_id, d.client_id, d.canonical_hostname,
               MAX(pp.last_seen) AS overall_last,
               jsonb_object_agg(pp.platform, pp.last_seen) AS per_source
        FROM per_platform pp
        JOIN operations.devices d
             ON d.id = pp.device_id AND d.tenant_id = pp.tenant_id
        WHERE d.deleted_at IS NULL
          AND d.lifecycle_status <> 'retired'
        GROUP BY pp.device_id, d.client_id, d.canonical_hostname
        HAVING MAX(pp.last_seen) < NOW() - %s::interval
        """,
        (tenant_id, threshold_interval),
    )
    count = 0
    offenders: list[uuid.UUID] = []
    for dev_id, client_id, hostname, overall_last, per_source in cur.fetchall():
        offenders.append(dev_id)
        # per_source is a dict {platform: iso_ts_string}; identify the
        # source that held on longest (== overall_last).
        last_seen_source = None
        if isinstance(per_source, dict) and per_source:
            last_seen_source = max(per_source, key=lambda k: per_source[k] or "")
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_offline", "")
        count += _upsert_finding(
            cur, tenant_id, ft_id, client_id, dev_id,
            ckey, "medium", "confirmed", now,
            {
                "hostname": hostname,
                "last_contact_at": overall_last.isoformat() if overall_last else None,
                "fully_offline_since": overall_last.isoformat() if overall_last else None,
                "source_last_seen": per_source or {},
                "last_seen_source": last_seen_source,
            },
        )
    _resolve_findings_absent(cur, tenant_id, ft_id, offenders, now)
    return count


def _evaluate_stale_data(cur: Any, tenant_id: int, now: datetime) -> int:
    """Devices no source has observed at all in the stale window."""
    ft_id = _get_finding_type_id(cur, "device_stale_data")
    if ft_id is None:
        return 0
    cur.execute(
        """
        SELECT apc.device_id, d.client_id, d.canonical_hostname,
               MAX(apc.last_observed_at)
        FROM operations.device_agent_presence_current apc
        JOIN operations.devices d
             ON d.id = apc.device_id AND d.tenant_id = apc.tenant_id
        WHERE apc.tenant_id = %s AND d.deleted_at IS NULL
        GROUP BY apc.device_id, d.client_id, d.canonical_hostname
        HAVING MAX(apc.last_observed_at) < now() - %s::interval
        """,
        (tenant_id, f"{_STALE_DATA_DAYS} days"),
    )
    count = 0
    offenders: list[uuid.UUID] = []
    for dev_id, client_id, hostname, last_observed in cur.fetchall():
        offenders.append(dev_id)
        ckey = _condition_key(tenant_id, client_id, dev_id, "device_stale_data", "")
        count += _upsert_finding(
            cur, tenant_id, ft_id, client_id, dev_id,
            ckey, "low", "confirmed", now,
            {
                "hostname": hostname,
                "last_observed_at": last_observed.isoformat() if last_observed else None,
            },
        )
    _resolve_findings_absent(cur, tenant_id, ft_id, offenders, now)
    return count


# cross_client_conflict emitter removed 2026-07-14.
# The finding was a legacy-AC port: "hostname X exists under multiple
# clients → possible identity issue." In the operations resolver the
# only way two devices can end up with the same hostname across clients
# is if they have DIFFERENT hardware (else the resolver would have
# merged them into ONE canonical device at resolve time). So this
# finding could ONLY fire on naming coincidence — 100% false positives
# on this fleet (0 of 1,685 pairs had hardware corroboration).
# BLUEPRINT §1.7 updated to reflect the removal.


# --------------------------------------------------------------------------
# 5. Auto-resolve
# --------------------------------------------------------------------------

def _auto_resolve(
    cur: Any,
    tenant_id: int,
    device_id: uuid.UUID | None,
    now: datetime,
) -> int:
    """Resolve findings where the condition has cleared."""
    count = 0

    # Resolve missing/stale_required_platform whose (entity_type, platform)
    # is no longer required by the device's client policy. Fires when the
    # operator changes a client's requirement_profile (or empties it) —
    # findings that were legitimate under the old policy become stale
    # once the policy is edited. Reconciles per (device, entity_type,
    # platform) tuple:
    #   * client has profile → required = union of profile.items scoped to
    #     the device's role or 'all'
    #   * client has no profile → required = union of global
    #     coverage_requirements scoped to the device's role or 'all'
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            """
            WITH required_for_device AS (
                -- Profile-bound clients: their profile.items are the truth
                SELECT d.id AS device_id, rpi.entity_type, rpi.platform
                FROM operations.devices d
                JOIN operations.clients c ON c.id = d.client_id
                JOIN operations.requirement_profile_items rpi
                  ON rpi.tenant_id = c.tenant_id
                 AND rpi.profile_id = c.requirement_profile_id
                 AND (rpi.device_scope = 'all' OR rpi.device_scope = d.device_role)
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
                  AND c.requirement_profile_id IS NOT NULL

                UNION

                -- Clients without a profile: fall through to global rows
                SELECT d.id AS device_id, cr.entity_type, cr.platform
                FROM operations.devices d
                JOIN operations.clients c ON c.id = d.client_id
                JOIN operations.coverage_requirements cr
                  ON cr.tenant_id = c.tenant_id
                 AND cr.client_id IS NULL AND cr.enabled
                 AND (cr.device_scope = 'all' OR cr.device_scope = d.device_role)
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
                  AND c.requirement_profile_id IS NULL
            )
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM required_for_device r
                  WHERE r.device_id = f.subject_id
                    AND r.entity_type = (f.finding_details->>'entity_type')
                    AND r.platform    = (f.finding_details->>'platform')
              )
            """,
            (tenant_id, tenant_id, now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve missing/stale_required_platform when the platform has
    # observed the device again recently.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type = (f.finding_details->>'entity_type')
                    AND apc.platform = (f.finding_details->>'platform')
                    AND COALESCE(apc.last_contact_at, apc.last_observed_at) > now() - INTERVAL '48 hours'
              )
            """,
            (now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve stale_required_platform on devices that are now fully
    # offline (BLUEPRINT §1.8): device_offline covers the whole
    # device, per-agent stale becomes noise. Reciprocal of the
    # suppression in _evaluate_coverage — closes legacy rows so they
    # don't linger after the emission gate kicks in.
    stale_ft_id = _get_finding_type_id(cur, "stale_required_platform")
    if stale_ft_id:
        # Non-correlated subquery — Postgres computes the
        # offline-device set once. Tenant is always the same for
        # the outer scope so it's safe to bind directly.
        cur.execute(
            f"""
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND f.subject_id IN (
                  SELECT apc.device_id
                  FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = %s
                    AND apc.entity_type LIKE 'agent.%%'
                  GROUP BY apc.device_id
                  HAVING MAX(COALESCE(apc.last_contact_at, apc.last_observed_at))
                       < NOW() - INTERVAL '{_LONG_OFFLINE_DAYS} days'
              )
            """,
            (now, tenant_id, stale_ft_id, device_id, device_id, tenant_id),
        )
        count += cur.rowcount or 0

    # Close any missing/stale_required_platform finding whose device left
    # the agent universe (no agent.* observation exists anymore). New
    # emission is already gated by the universe filter in
    # _evaluate_coverage; this closes legacy rows so they don't linger.
    for ft_name in ("missing_required_platform", "stale_required_platform"):
        ft_id = _get_finding_type_id(cur, ft_name)
        if not ft_id:
            continue
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type LIKE 'agent.%%'
              )
            """,
            (now, tenant_id, ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve device_unenrolled when the device joins the agent universe
    # (any agent.* observation appears).
    unenrolled_ft_id = _get_finding_type_id(cur, "device_unenrolled")
    if unenrolled_ft_id:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved', last_seen_at = %s
            WHERE f.tenant_id = %s AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND EXISTS (
                  SELECT 1 FROM operations.device_agent_presence_current apc
                  WHERE apc.tenant_id = f.tenant_id
                    AND apc.device_id = f.subject_id
                    AND apc.entity_type LIKE 'agent.%%'
              )
            """,
            (now, tenant_id, unenrolled_ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    # Resolve device_missing_from_source if device_links.missing_since cleared
    missing_ft_id = _get_finding_type_id(cur, "device_missing_from_source")
    if missing_ft_id:
        cur.execute(
            """
            UPDATE operations.findings f
            SET status = 'resolved',
                last_seen_at = %s
            WHERE f.tenant_id = %s
              AND f.finding_type_id = %s
              AND f.status IN ('open', 'acknowledged')
              AND (%s::uuid IS NULL OR f.subject_id = %s)
              AND NOT EXISTS (
                  SELECT 1 FROM operations.device_links dl
                  WHERE dl.device_id = f.subject_id
                    AND dl.tenant_id = f.tenant_id
                    AND dl.missing_since IS NOT NULL
              )
            """,
            (now, tenant_id, missing_ft_id, device_id, device_id),
        )
        count += cur.rowcount or 0

    return count


def _resolve_findings_absent(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    current_subject_ids: list[uuid.UUID],
    now: datetime,
) -> None:
    """Resolve open findings of a type whose subject is no longer an offender."""
    cur.execute(
        """
        UPDATE operations.findings
        SET status = 'resolved', last_seen_at = %s
        WHERE tenant_id = %s
          AND finding_type_id = %s
          AND status IN ('open', 'acknowledged')
          AND NOT (subject_id = ANY(%s::uuid[]))
        """,
        (now, tenant_id, finding_type_id, current_subject_ids),
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_finding_type_cache: dict[str, int] = {}


def _get_finding_type_id(cur: Any, name: str) -> int | None:
    if name in _finding_type_cache:
        return _finding_type_cache[name]
    cur.execute(
        "SELECT id FROM operations.finding_types WHERE name = %s LIMIT 1",
        (name,),
    )
    row = cur.fetchone()
    if row:
        _finding_type_cache[name] = row[0]
        return row[0]
    return None


def _condition_key(
    tenant_id: int,
    client_id: Any,
    device_id: uuid.UUID,
    finding_type: str,
    platform: str,
) -> str:
    raw = f"{tenant_id}:{client_id}:{device_id}:{finding_type}:{platform}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _upsert_finding(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    client_id: Any,
    device_id: uuid.UUID,
    condition_key: str,
    severity: str,
    confidence: str,
    now: datetime,
    details: dict[str, Any],
) -> int:
    """UPSERT a finding. Severity is immutable; confidence and timestamps update."""
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, finding_details,
            condition_key, severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, %s,
            'device', %s, %s::jsonb,
            %s, %s, %s, 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
            WHERE condition_key > '' AND status IN ('open', 'acknowledged')
        DO UPDATE SET
            confidence      = EXCLUDED.confidence,
            last_seen_at    = EXCLUDED.last_seen_at,
            last_detected_at = EXCLUDED.last_detected_at,
            status          = CASE
                WHEN findings.status = 'resolved' THEN 'open'
                ELSE findings.status
            END
        """,
        (
            tenant_id, finding_type_id, client_id,
            device_id, json.dumps(details),
            condition_key, severity, confidence,
            now, now, now,
        ),
    )
    return 1
