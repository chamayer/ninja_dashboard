"""Computer identity findings (ADR-0032).

Two conditions, both derived from what the current records of each Computer
report now, with the Computer as subject:

* ``two_machines_on_one_computer``: the active agent or VM records of one
  Computer report two usable serials or two VM UUIDs, or two agents of one
  source reported different names within one day with no shared serial. The
  finding proposes which records to split off: the machine whose name is the
  Computer's name stays, otherwise the machine with the most records.
* ``duplicate_device_records``: live Computers in one client with the same
  name and nothing linking or separating them (no shared or differing serial
  or VM UUID, no two records of one source online at once, and no operator
  decision that they are separate). One finding per group, subject the most
  recently active member.

Both write a measured assessment each run, so a finding clears on the first
run after its condition ends (a merge, a split, a source correction, or an
operator's "confirmed separate").
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from ingest.condition_evidence import preserve_operator_episode
from ingest.conditions import record_assessment
from ingest import normalize
from ingest.identity.matching import loose_name
from ingest.normalize import is_usable_serial
from shared.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Readiness,
    Signal,
)

log = logging.getLogger(__name__)

TWO_MACHINES = "two_machines_on_one_computer"
DUPLICATE_COMPUTERS = "duplicate_device_records"
_SAME_NAME_WINDOW = timedelta(days=1)
_RECENT = timedelta(days=30)

# Active records of current Computers. Agent and VM records are hardware
# evidence; other records only make a Computer live.
_RECORDS = """
SELECT d.id, d.client_id, d.canonical_hostname, d.created_at,
       eo.observation_id, eo.platform, eo.entity_type, eo.entity_key,
       lower(split_part(coalesce(eo.canonical_data ->> 'hostname', ''), '.', 1)),
       eo.canonical_data ->> 'serial_number',
       lower(nullif(trim(eo.canonical_data ->> 'vm_uuid'), '')),
       coalesce((eo.canonical_data ->> 'is_online')::boolean, false),
       eo.last_seen_at
  FROM operations.devices d
  JOIN operations.entity_observation_current eo
    ON eo.tenant_id = d.tenant_id AND eo.device_id = d.id
 WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND eo.active
   AND eo.entity_key NOT LIKE 'device-health:%%'
"""

_SEPARATED = """
SELECT device_id, k.value
  FROM operations.device_operator_decisions, jsonb_array_elements_text(value) k
 WHERE tenant_id = %s AND dimension = 'identity_separate'
"""


class _Computer:
    __slots__ = ("id", "client_id", "name", "created_at", "records")

    def __init__(self, device_id, client_id, name, created_at):
        self.id = device_id
        self.client_id = client_id
        self.name = name or ""
        self.created_at = created_at
        self.records: list[dict[str, Any]] = []

    @property
    def hardware(self) -> list[dict[str, Any]]:
        return [
            r
            for r in self.records
            if r["entity_type"].startswith("agent.") or r["entity_type"].startswith("vm.")
        ]

    @property
    def serials(self) -> set[str]:
        return {r["serial"] for r in self.hardware if r["serial"]}

    @property
    def vm_uuids(self) -> set[str]:
        return {r["vm_uuid"] for r in self.hardware if r["vm_uuid"]}

    @property
    def online_streams(self) -> set[str]:
        return {r["stream"] for r in self.hardware if r["online"]}

    @property
    def last_active(self):
        return max((r["last_seen_at"] for r in self.records if r["last_seen_at"]), default=None)


def evaluate(cur: Any, tenant_id: int, now: datetime) -> int:
    """Raise and clear both identity conditions; return findings written."""
    # Without the serial rejection list no serial is usable, which would read
    # as "no two machines anywhere" and clear every finding: skip instead.
    normalize.load_identity_value_rejections(cur)
    if normalize._serial_rejection_cache is None:
        log.warning("identity findings: serial rejections unavailable, skipped")
        return 0
    computers = _load(cur, tenant_id)
    written = 0
    ft_two = _finding_type_id(cur, TWO_MACHINES)
    if ft_two is not None:
        keys = []
        for computer in computers.values():
            proposal = two_machines(computer, now)
            if proposal is None:
                continue
            key = _key(tenant_id, TWO_MACHINES, computer.id)
            keys.append(key)
            written += _upsert(
                cur, tenant_id, ft_two, computer.client_id, computer.id, key, "high", now, proposal
            )
        resolve_absent(cur, tenant_id, ft_two, keys, now)
    ft_dup = _finding_type_id(cur, DUPLICATE_COMPUTERS)
    if ft_dup is not None:
        keys = []
        for subject, details in duplicate_groups(computers, _separated(cur, tenant_id)):
            key = _key(
                tenant_id, DUPLICATE_COMPUTERS, subject.client_id, loose_name(subject.name),
                min(str(m["device_id"]) for m in details["computers"]),
            )
            keys.append(key)
            written += _upsert(
                cur, tenant_id, ft_dup, subject.client_id, subject.id, key, "medium", now, details
            )
        resolve_absent(cur, tenant_id, ft_dup, keys, now)
    return written


def _load(cur: Any, tenant_id: int) -> dict[uuid.UUID, _Computer]:
    cur.execute(_RECORDS, (tenant_id,))
    computers: dict[uuid.UUID, _Computer] = {}
    for (
        device_id, client_id, name, created_at, observation_id, platform, entity_type,
        entity_key, host, serial, vm_uuid, online, last_seen_at,
    ) in cur.fetchall():
        computer = computers.get(device_id)
        if computer is None:
            computer = computers[device_id] = _Computer(device_id, client_id, name, created_at)
        computer.records.append(
            {
                "observation_id": observation_id,
                "platform": platform,
                "entity_type": entity_type,
                "entity_key": entity_key,
                "stream": f"{platform}:{entity_type}",
                "hostname": host or "",
                "serial": serial.strip().lower() if is_usable_serial(serial) else None,
                "vm_uuid": vm_uuid,
                "online": online,
                "last_seen_at": last_seen_at,
            }
        )
    return computers


def two_machines(computer: _Computer, now: datetime) -> dict[str, Any] | None:
    """The machines a Computer's records show, when there is more than one."""
    records = computer.hardware
    if len(computer.serials) > 1:
        kind, value_of = "serial", lambda r: r["serial"]
    elif len(computer.vm_uuids) > 1:
        kind, value_of = "vm_uuid", lambda r: r["vm_uuid"]
    elif _two_names_in_one_source(records, now):
        kind, value_of = "hostname", lambda r: r["hostname"] or None
    else:
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    unplaced: list[dict[str, Any]] = []
    for record in records:
        value = value_of(record)
        (groups.setdefault(value, []) if value else unplaced).append(record)
    # A record without the dividing value joins the machine with its name.
    for record in unplaced:
        home = next(
            (
                value
                for value, members in groups.items()
                if record["hostname"] and any(m["hostname"] == record["hostname"] for m in members)
            ),
            None,
        )
        if home is not None:
            groups[home].append(record)
    own = loose_name(computer.name)

    def rank(item):
        _value, members = item
        named = any(loose_name(m["hostname"]) == own for m in members)
        seen = max((m["last_seen_at"] for m in members if m["last_seen_at"]), default=None)
        return (named, len(members), seen.timestamp() if seen else 0)

    keep = max(groups.items(), key=rank)[0]
    machines = [
        {
            kind: value,
            "keep": value == keep,
            "hostnames": sorted({m["hostname"] for m in members if m["hostname"]}),
            "records": [_record_detail(m) for m in members],
        }
        for value, members in sorted(groups.items(), key=lambda item: item[0] != keep)
    ]
    return {
        "hostname": computer.name,
        "divided_by": kind,
        "machine_count": len(machines),
        "machines": machines,
        "proposed_split_observation_ids": [
            str(m["observation_id"])
            for value, members in groups.items()
            if value != keep
            for m in members
        ],
    }


def _two_names_in_one_source(records: list[dict[str, Any]], now: datetime) -> bool:
    """Two agents of one source report different names within one day."""
    agents = [
        r
        for r in records
        if r["entity_type"].startswith("agent.")
        and r["hostname"]
        and r["last_seen_at"]
        and r["last_seen_at"] > now - _RECENT
    ]
    for i, x in enumerate(agents):
        for y in agents[i + 1 :]:
            if (
                x["stream"] == y["stream"]
                and x["hostname"] != y["hostname"]
                and abs(x["last_seen_at"] - y["last_seen_at"]) < _SAME_NAME_WINDOW
                and not (x["serial"] and x["serial"] == y["serial"])
            ):
                return True
    return False


def duplicate_groups(
    computers: dict[uuid.UUID, _Computer], separated: set[tuple[str, str]]
) -> list[tuple[_Computer, dict[str, Any]]]:
    """Same-name live Computers that nothing links or separates."""
    by_name: dict[tuple, list[_Computer]] = {}
    for computer in computers.values():
        name = loose_name(computer.name)
        if name:
            by_name.setdefault((computer.client_id, name), []).append(computer)
    found = []
    for members in by_name.values():
        if len(members) < 2:
            continue
        # Name-only pairs, joined into groups.
        parent = {m.id: m.id for m in members}

        def root(device_id):
            while parent[device_id] != device_id:
                device_id = parent[device_id]
            return device_id

        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if _name_only_pair(a, b, separated):
                    parent[root(a.id)] = root(b.id)
        components: dict[uuid.UUID, list[_Computer]] = {}
        for member in members:
            components.setdefault(root(member.id), []).append(member)
        for group in components.values():
            if len(group) < 2:
                continue
            group.sort(
                key=lambda c: (
                    -(c.last_active.timestamp() if c.last_active else 0),
                    c.created_at,
                    str(c.id),
                )
            )
            # Members joined only through a name-only member can still be
            # proven different from each other; they must never be merged.
            different = [
                [str(a.id), str(b.id)]
                for i, a in enumerate(group)
                for b in group[i + 1 :]
                if _different_machines(a, b)
            ]
            found.append(
                (
                    group[0],
                    {
                        "hostname": group[0].name,
                        "computer_count": len(group),
                        "different_machines": different,
                        "computers": [
                            {
                                "device_id": str(c.id),
                                "hostname": c.name,
                                "serials": sorted(c.serials),
                                "platforms": sorted({r["platform"] for r in c.records}),
                                "last_active_at": c.last_active.isoformat()
                                if c.last_active
                                else None,
                            }
                            for c in group
                        ],
                    },
                )
            )
    return found


def _name_only_pair(a: _Computer, b: _Computer, separated: set[tuple[str, str]]) -> bool:
    if (str(a.id), str(b.id)) in separated or (str(b.id), str(a.id)) in separated:
        return False
    # Linked (one machine, merged automatically or a shared_serial case) or
    # proven different: either way not a name-only question.
    if a.serials and b.serials:
        return False
    if a.vm_uuids and b.vm_uuids:
        return False
    return not (a.online_streams & b.online_streams)


def _different_machines(a: _Computer, b: _Computer) -> bool:
    if a.serials and b.serials and not (a.serials & b.serials):
        return True
    if a.vm_uuids and b.vm_uuids and not (a.vm_uuids & b.vm_uuids):
        return True
    return bool(a.online_streams & b.online_streams)


def _record_detail(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(record["observation_id"]),
        "platform": record["platform"],
        "entity_type": record["entity_type"],
        "hostname": record["hostname"],
        "serial": record["serial"],
        "vm_uuid": record["vm_uuid"],
        "online": record["online"],
        "last_seen_at": record["last_seen_at"].isoformat() if record["last_seen_at"] else None,
    }


def _separated(cur: Any, tenant_id: int) -> set[tuple[str, str]]:
    cur.execute(_SEPARATED, (tenant_id,))
    return {(str(device_id), other) for device_id, other in cur.fetchall()}


def _finding_type_id(cur: Any, name: str) -> int | None:
    cur.execute("SELECT id FROM operations.finding_types WHERE name = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def _key(*parts: Any) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:64]


def _upsert(
    cur: Any,
    tenant_id: int,
    finding_type_id: int,
    client_id: Any,
    device_id: uuid.UUID,
    condition_key: str,
    severity: str,
    now: datetime,
    details: dict[str, Any],
) -> int:
    preserved = preserve_operator_episode(cur, "findings", tenant_id, condition_key, now, details)
    if preserved is not None:
        finding_id = uuid.UUID(preserved)
    else:
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, subject_layer, finding_details,
                condition_key, severity, confidence, status,
                first_seen_at, last_seen_at, last_detected_at
            ) VALUES (
                gen_random_uuid(), 1, %s, %s, %s, 'device', %s, '', %s::jsonb,
                %s, %s, 'confirmed', 'open', %s, %s, %s
            )
            ON CONFLICT (tenant_id, condition_key)
                WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                subject_id       = EXCLUDED.subject_id,
                client_id        = EXCLUDED.client_id,
                finding_details  = EXCLUDED.finding_details,
                last_seen_at     = EXCLUDED.last_seen_at,
                last_detected_at = EXCLUDED.last_detected_at
            RETURNING id
            """,
            (
                tenant_id, finding_type_id, client_id, device_id, json.dumps(details),
                condition_key, severity, now, now, now,
            ),
        )
        finding_id = cur.fetchone()[0]
    record_measured(cur, tenant_id, finding_id, finding_type_id, condition_key, device_id, now)
    return 1


def record_measured(cur, tenant_id, finding_id, finding_type_id, condition_key, device_id, now):
    cur.execute("SELECT name FROM operations.finding_types WHERE id = %s", (finding_type_id,))
    participant = Participant("device", str(device_id), "affected", tenant_id)
    record_assessment(
        cur,
        Condition(
            tenant_id, "entity", str(finding_id), cur.fetchone()[0], condition_key, "open",
            (participant,),
        ),
        (Signal("collection", participant, Readiness.READY, "collection:complete_snapshot"),),
        EvaluationCoverage(True, True, True, True),
        now=now,
        reevaluation_key=f"identity:{condition_key}",
        participant=participant,
    )


def resolve_absent(cur: Any, tenant_id: int, finding_type_id: int, keys: list[str], now) -> None:
    """Close findings whose condition this complete run no longer found."""
    cur.execute(
        """
        UPDATE operations.findings f
           SET status = 'resolved', last_seen_at = %s
         WHERE f.tenant_id = %s AND f.finding_type_id = %s
           AND f.status IN ('open', 'acknowledged')
           AND NOT (f.condition_key = ANY(%s::text[]))
           AND EXISTS (
               SELECT 1
                 FROM operations.condition_assessments assessment
                 JOIN operations.condition_policy_versions policy
                   ON policy.version = assessment.policy_version AND policy.active
                WHERE assessment.tenant_id = f.tenant_id
                  AND assessment.row_kind = 'entity'
                  AND assessment.finding_id = f.id
                  AND (assessment.response ->> 'may_clear')::boolean IS TRUE
                  AND assessment.assessed_at >= now() -
                      (policy.policy ->> 'freshness_hours')::integer * interval '1 hour'
           )
        """,
        (now, tenant_id, finding_type_id, keys),
    )
    if cur.rowcount:
        log.info("identity findings: cleared %d (type %s)", cur.rowcount, finding_type_id)
