"""Per-device condition readiness for software finding types (design D1, D4).

The condition engine decides, under the active policy, whether a device may be
acted on or notified for a finding type. That answer depends on the device
(identity settled, recent agent contact) and the finding type's rules, never on
which software finding the device takes part in. The previous classifier asked
it again for every (finding, device) pair; this module asks once per (device,
software finding type) and stores the decision in
``operations.software_device_readiness``.

Inputs are loaded set-based: the per-device identity query used by the previous
path took longer than 58 seconds for the fleet; the form below takes under a
second.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from ingest import db, device_status_settings
from ingest.condition_evidence import offline_readiness
from ingest.conditions import load_active_profile
from shared.conditions.contracts import Condition, Participant, Readiness, Signal
from shared.conditions.engine import assess
from shared.conditions.policy import Profile

log = logging.getLogger(__name__)

# One row per live device: whether it is attached to an identity and a client,
# and whether an unreviewed identity conflict names it. Same predicates as
# ``condition_evidence.device_identity_signals``, evaluated once for the fleet.
IDENTITY_SQL = """
WITH conflicts AS (
    SELECT finding.subject_id, finding.finding_details
      FROM operations.findings finding
      JOIN operations.finding_types finding_type
        ON finding_type.id = finding.finding_type_id
     WHERE finding.tenant_id = %(tenant_id)s
       AND finding_type.name = 'identity_conflict'
       AND finding.status IN ('open', 'acknowledged', 'investigating', 'suppressed')
       AND NOT EXISTS (
           SELECT 1
             FROM operations.condition_reviewed_distinct reviewed
            WHERE reviewed.tenant_id = finding.tenant_id
              AND reviewed.condition_identity = finding.condition_key
              AND reviewed.membership_fingerprint = encode(pg_catalog.sha256(convert_to(
                  (finding.finding_details->'candidate_device_ids')::text, 'UTF8')), 'hex')
              AND reviewed.evidence_fingerprint = encode(pg_catalog.sha256(convert_to(
                  finding.finding_details::text, 'UTF8')), 'hex')
       )
), conflicted AS (
    SELECT subject_id::text AS device_key FROM conflicts WHERE subject_id IS NOT NULL
    UNION
    SELECT candidate.value
      FROM conflicts
     CROSS JOIN LATERAL jsonb_array_elements_text(
         CASE WHEN jsonb_typeof(conflicts.finding_details->'candidate_device_ids') = 'array'
              THEN conflicts.finding_details->'candidate_device_ids'
              ELSE '[]'::jsonb END
     ) AS candidate(value)
)
SELECT device.id::text,
       device.entity_id IS NOT NULL AND device.client_id IS NOT NULL AS attached,
       conflicted.device_key IS NOT NULL AS conflicted
  FROM operations.devices device
  LEFT JOIN conflicted ON conflicted.device_key = device.id::text
 WHERE device.tenant_id = %(tenant_id)s AND device.deleted_at IS NULL
"""

CONTACT_SQL = """
SELECT device_id::text, MAX(COALESCE(last_contact_at, last_observed_at))
  FROM operations.device_agent_presence_current
 WHERE tenant_id = %(tenant_id)s AND platform = 'Ninja'
 GROUP BY device_id
"""

# The software finding types are the ones the software emitters register
# (their ``source_module``). That names code, not a domain value, so it is a
# query predicate rather than a configurable mapping.
TYPES_SQL = """
SELECT id, name
  FROM operations.finding_types
 WHERE source_module IN ('platform.software_findings', 'platform.capability_match')
 ORDER BY id
"""

READINESS_COLUMNS = (
    "tenant_id, device_id, finding_type_id, policy_version, policy_digest, "
    "disposition, may_notify, may_execute, reasons, blockers, assessed_at"
)


def identity_signal(participant: Participant, attached: bool, conflicted: bool) -> Signal:
    if conflicted:
        return Signal("identity", participant, Readiness.BLOCKED, "identity:unsettled_group")
    if attached:
        return Signal("identity", participant, Readiness.READY, "identity:stable_attachment")
    return Signal("identity", participant, Readiness.UNKNOWN, "identity:readiness_not_measured")


def compute(
    *,
    tenant_id: int,
    devices: Iterable[tuple[str, bool, bool]],
    contacts: Mapping[str, datetime | None],
    finding_types: Iterable[tuple[int, str]],
    profile: Profile,
    now: datetime,
    offline_days: int,
) -> list[tuple]:
    """Return one readiness row per (device, finding type). Pure; no I/O."""
    types = list(finding_types)
    rows: list[tuple] = []
    for device_id, attached, conflicted in devices:
        participant = Participant("device", str(device_id), "affected", tenant_id)
        offline_state, offline_reason = offline_readiness(
            [contacts.get(str(device_id))], now=now, offline_days=offline_days
        )
        signals = (
            identity_signal(participant, bool(attached), bool(conflicted)),
            Signal("offline", participant, offline_state, offline_reason),
        )
        for type_id, type_name in types:
            condition = Condition(
                tenant_id, "entity", f"readiness:{device_id}", type_name, "", "open",
                (participant,),
            )
            decision = assess(condition, profile, signals, now, participant)
            rows.append(
                (
                    tenant_id, str(device_id), type_id, profile.version, profile.digest,
                    decision.disposition, decision.may_notify, decision.may_execute,
                    list(decision.reasons), list(decision.blockers), now,
                )
            )
    return rows


def _offline_days(cur: Any, tenant_id: int) -> int:
    # The tenant's single "offline after" setting (Device status page).
    return device_status_settings.load(cur, tenant_id)[0]


def refresh(tenant_id: int = 1, *, now: datetime | None = None) -> int:
    """Rebuild every readiness row for the tenant in one transaction."""
    now = now or datetime.now(timezone.utc)
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {int(tenant_id)}")
        profile = load_active_profile(cur)
        cur.execute(TYPES_SQL)
        finding_types = cur.fetchall()
        cur.execute(IDENTITY_SQL, {"tenant_id": tenant_id})
        devices = cur.fetchall()
        cur.execute(CONTACT_SQL, {"tenant_id": tenant_id})
        contacts = {str(device_id): contact for device_id, contact in cur.fetchall()}
        rows = compute(
            tenant_id=tenant_id, devices=devices, contacts=contacts,
            finding_types=finding_types, profile=profile, now=now,
            offline_days=_offline_days(cur, tenant_id),
        )
        columns = READINESS_COLUMNS
        cur.execute(
            "CREATE TEMP TABLE software_device_readiness_next "
            "(LIKE operations.software_device_readiness INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        with cur.copy(f"COPY software_device_readiness_next ({columns}) FROM STDIN") as copy:
            copy.set_types(
                [
                    "bigint", "uuid", "smallint", "text", "text", "text", "bool", "bool",
                    "text[]", "text[]", "timestamptz",
                ]
            )
            for row in rows:
                copy.write_row(row)
        cur.execute(
            f"""
            INSERT INTO operations.software_device_readiness ({columns})
            SELECT {columns} FROM software_device_readiness_next
            ON CONFLICT (tenant_id, device_id, finding_type_id) DO UPDATE SET
                policy_version = EXCLUDED.policy_version,
                policy_digest = EXCLUDED.policy_digest,
                disposition = EXCLUDED.disposition,
                may_notify = EXCLUDED.may_notify,
                may_execute = EXCLUDED.may_execute,
                reasons = EXCLUDED.reasons,
                blockers = EXCLUDED.blockers,
                assessed_at = EXCLUDED.assessed_at
            """
        )
        cur.execute(
            """
            DELETE FROM operations.software_device_readiness current
             WHERE current.tenant_id = %s
               AND NOT EXISTS (
                   SELECT 1 FROM software_device_readiness_next next
                    WHERE next.device_id = current.device_id
                      AND next.finding_type_id = current.finding_type_id
               )
            """,
            (tenant_id,),
        )
        removed = cur.rowcount
    log.info("software_readiness: tenant=%d rows=%d removed=%d", tenant_id, len(rows), removed)
    return len(rows)
