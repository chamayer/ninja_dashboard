"""What lists a Computer now, and what that means for it (ADR-0032 "Retirement").

A record's lifecycle comes from ``operations.source_record_lifecycle_mappings``
through ``v_device_source_record_lifecycle_current``: a current Hudu asset is
``documentation``, an archived one ``archived``, a powered-off or suspended VM
``stopped``; none of them is evidence that the machine exists. Every other
current record (agent, monitor, network device, running VM) is evidence.

"Reporting" means an evidence record that is online, or whose source last
contacted the machine within 30 days, or a running VM. Silent agents are
evidence but not reporting; they stay with the offline handling.

States, with the Computer's lifecycle and finding:

==========================  ===============  ===================================
state                       lifecycle        finding
==========================  ===============  ===================================
reporting / silent          contact policy   (offline handling)
archived_but_reporting      contact policy   archived_but_reporting
archived_still_listed       pending_cleanup  device_missing_from_source
stopped_vm_only             pending_cleanup  device_missing_from_source
documentation_only          pending_cleanup  device_missing_from_source
nothing_listed              pending_cleanup  device_missing_from_source
confirmed_in_use            pending_cleanup  (coverage check: missing agents)
retire                      retired          (none; restored when it reports)
==========================  ===============  ===================================

``retire``: nothing lists the machine, and Hudu has no asset for it or every
asset is archived. Without any Hudu asset, retirement waits for the review
period after the last record was seen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

REPORTING_WINDOW = timedelta(days=30)

CONTACT_POLICY_STATES = frozenset({"reporting", "silent", "archived_but_reporting"})
CLEANUP_STATES = frozenset(
    {"archived_still_listed", "stopped_vm_only", "documentation_only", "nothing_listed"}
)
# Review without a cleanup finding: the operator confirmed the machine in use.
REVIEW_STATES = CLEANUP_STATES | {"confirmed_in_use"}
CLEANUP_REASONS = {
    "archived_still_listed": "archived_still_listed",
    "stopped_vm_only": "stopped_vm_only",
    "documentation_only": "documentation_only",
    "nothing_listed": "nothing_listed",
}

LISTING_SQL = """
SELECT d.id, d.client_id, d.lifecycle_status,
       coalesce(bool_or(r.counts_as_current_computer_evidence), false) AS evidence,
       coalesce(bool_or(r.counts_as_current_computer_evidence AND (
           coalesce((r.canonical_data ->> 'is_online')::boolean, false)
           OR lower(coalesce(r.canonical_data ->> 'power_state', '')) = 'poweredon'
           OR r.last_contact_at > %(now)s::timestamptz - %(window)s::interval)), false)
           AS reporting,
       coalesce(bool_or(r.source_record_current AND r.record_lifecycle = 'documentation'), false)
           AS documentation,
       coalesce(bool_or(r.source_record_current AND r.record_lifecycle = 'archived'), false)
           AS archived,
       coalesce(bool_or(r.source_record_current AND r.record_lifecycle = 'stopped'), false)
           AS stopped,
       max(r.last_seen_at) AS last_seen_at,
       (array_agg(r.source_name ORDER BY r.last_seen_at DESC NULLS LAST)
            FILTER (WHERE r.observation_id IS NOT NULL))[1] AS last_source,
       EXISTS (SELECT 1 FROM operations.device_operator_decisions dec
                WHERE dec.tenant_id = d.tenant_id AND dec.device_id = d.id
                  AND dec.dimension = 'in_use_confirmed' AND dec.value = 'true'::jsonb)
           AS in_use_confirmed
  FROM operations.devices d
  LEFT JOIN (
      -- Ninja's device-health rows describe a Computer; they are not a record of it.
      SELECT rec.*, obs.canonical_data, apc.last_contact_at
        FROM operations.v_device_source_record_lifecycle_current rec
        JOIN operations.entity_observation_current obs
          ON obs.tenant_id = rec.tenant_id AND obs.observation_id = rec.observation_id
        LEFT JOIN operations.device_agent_presence_current apc
          ON apc.tenant_id = obs.tenant_id AND apc.device_id = obs.device_id
         AND apc.platform = obs.platform AND apc.entity_type = obs.entity_type
       WHERE obs.entity_key NOT LIKE 'device-health:%%'
  ) r ON r.tenant_id = d.tenant_id AND r.device_id = d.id
 WHERE d.tenant_id = %(tenant)s AND d.deleted_at IS NULL
   AND (%(device)s::uuid IS NULL OR d.id = %(device)s::uuid)
 GROUP BY d.id, d.client_id, d.lifecycle_status
"""


@dataclass(frozen=True)
class Listing:
    device_id: uuid.UUID
    client_id: uuid.UUID
    lifecycle_status: str
    evidence: bool
    reporting: bool
    documentation: bool
    archived: bool
    stopped: bool
    last_seen_at: datetime | None
    last_source: str | None
    in_use_confirmed: bool = False

    def state(self, now: datetime, review_days: int) -> str:
        state = self._listing_state(now, review_days)
        # An operator confirmed it in use: it stays in review and in the
        # coverage check instead of a cleanup finding or retirement.
        if self.in_use_confirmed and (state in CLEANUP_STATES or state == "retire"):
            return "confirmed_in_use"
        return state

    def _listing_state(self, now: datetime, review_days: int) -> str:
        if self.archived and not self.documentation:
            if self.reporting:
                return "archived_but_reporting"
            if self.evidence or self.stopped:
                return "archived_still_listed"
            return "retire"
        if self.reporting:
            return "reporting"
        if self.evidence:
            return "silent"
        if self.stopped:
            return "stopped_vm_only"
        if self.documentation:
            return "documentation_only"
        if self.last_seen_at is None or self.last_seen_at < now - timedelta(days=review_days):
            return "retire"
        return "nothing_listed"


def load(cur: Any, tenant_id: int, now: datetime, device_id: uuid.UUID | None = None) -> list[Listing]:
    cur.execute(
        LISTING_SQL,
        {
            "tenant": tenant_id,
            "device": device_id,
            "now": now,
            "window": f"{REPORTING_WINDOW.days} days",
        },
    )
    return [Listing(*row) for row in cur.fetchall()]
