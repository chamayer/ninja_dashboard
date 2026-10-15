"""Which open findings cover a finding on the same computer.

``finding_types.covered_by`` lists the parent types that make a finding
redundant. While one of them has an open finding on the same computer, the
finding is covered: the condition engine sees a blocked ``parent_open`` rule
(effect: suppress attention), so the finding stays real and evaluated but is
not separate work. Chains are followed to the root-most open parent, so the
reference always names a finding that is itself visible.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any

from shared.conditions.contracts import Condition, Readiness, Signal

RULE = "parent_open"
OPEN_STATUSES = ("open", "acknowledged", "investigating")
_CACHE_SECONDS = 30.0
_cache: dict[str, Any] = {"at": 0.0, "map": {}}


def covered_by_map(cur: Any, *, use_cache: bool = True) -> dict[str, list[str]]:
    """Type name -> parent type names, for the types that have parents."""
    now = time.monotonic()
    if use_cache and now - _cache["at"] < _CACHE_SECONDS:
        return _cache["map"]
    cur.execute(
        "SELECT name, covered_by FROM operations.finding_types "
        "WHERE jsonb_array_length(covered_by) > 0"
    )
    mapping = {name: list(parents) for name, parents in cur.fetchall()}
    _cache.update(at=now, map=mapping)
    return mapping


def ancestors(type_name: str, covered: Mapping[str, list[str]]) -> set[str]:
    """Every type that covers ``type_name``, directly or through a chain."""
    found: set[str] = set()
    pending = list(covered.get(type_name, ()))
    while pending:
        parent = pending.pop()
        if parent in found:
            continue
        found.add(parent)
        pending.extend(covered.get(parent, ()))
    return found


def root_open_types(
    type_name: str, open_types: Iterable[str], covered: Mapping[str, list[str]]
) -> list[str]:
    """The open parent types that are not themselves covered by another open parent.

    These are the root-most open parents: the findings that stay visible and carry
    the "N hidden" count.
    """
    candidates = ancestors(type_name, covered) & set(open_types)
    return sorted(
        parent for parent in candidates if not ancestors(parent, covered) & candidates
    )


def cover_signals(cur: Any, condition: Condition) -> tuple[Signal, ...]:
    """One ``parent_open`` signal per participant: blocked when covered, ready otherwise.

    The signal is always emitted for a participant, because the engine reads a missing
    signal as unknown and would hold the finding.
    """
    covered = covered_by_map(cur)
    parents = ancestors(condition.type_name, covered)
    devices = [
        p
        for p in condition.participants
        if parents and p.kind == "device" and p.role == "affected" and condition.row_kind == "entity"
    ]
    roots_by_device: dict[str, tuple[list[str], list[str]]] = {}
    if devices:
        cur.execute(
            """
            SELECT f.subject_id::text, f.id::text, ft.name
              FROM operations.findings f
              JOIN operations.finding_types ft ON ft.id = f.finding_type_id
             WHERE f.tenant_id = %s
               AND f.subject_type = 'device'
               AND f.subject_id = ANY(%s::uuid[])
               AND ft.name = ANY(%s)
               AND f.status = ANY(%s)
            """,
            (
                condition.tenant_id,
                [p.reference for p in devices],
                sorted(parents),
                list(OPEN_STATUSES),
            ),
        )
        open_by_device: dict[str, dict[str, str]] = {}
        for subject_id, finding_id, type_name in cur.fetchall():
            open_by_device.setdefault(subject_id, {})[type_name] = finding_id
        for device_id, open_types in open_by_device.items():
            roots = root_open_types(condition.type_name, open_types, covered)
            if roots:
                roots_by_device[device_id] = (roots, [open_types[root] for root in roots])
    signals = []
    for participant in condition.participants:
        roots, finding_ids = roots_by_device.get(participant.reference, ([], []))
        if roots and participant.kind == "device":
            signals.append(
                Signal(
                    RULE,
                    participant,
                    Readiness.BLOCKED,
                    f"covered_by:{roots[0]}",
                    tuple(finding_ids),
                )
            )
        else:
            signals.append(Signal(RULE, participant, Readiness.READY, "parent_open:none"))
    return tuple(signals)
