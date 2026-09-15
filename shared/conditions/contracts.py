"""Pure, non-persisting contracts shared by shadow readers and policy tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cached_property


class Readiness(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class Participant:
    kind: str
    reference: str
    role: str
    tenant_id: int

    def __post_init__(self):
        if not self.kind or not self.reference or not self.role or self.tenant_id <= 0:
            raise ValueError("Participants require a kind, reference, role and owning tenant")


@dataclass(frozen=True)
class Condition:
    tenant_id: int
    row_kind: str
    row_id: str
    type_name: str
    condition_key: str
    status: str
    participants: tuple[Participant, ...] = ()
    snoozed_until: datetime | None = None

    def __post_init__(self):
        if self.row_kind not in ("entity", "admin") or self.tenant_id <= 0 or not self.row_id:
            raise ValueError("Invalid legacy condition reference")
        if any(p.tenant_id != self.tenant_id for p in self.participants):
            raise ValueError("Cross-tenant condition participant")
        if self.status not in {
            "open",
            "acknowledged",
            "investigating",
            "suppressed",
            "resolved",
            "wontfix",
        }:
            raise ValueError("Unknown legacy handling state")
        if self.snoozed_until is not None and self.snoozed_until.tzinfo is None:
            raise ValueError("Snooze time must be timezone-aware")

    @cached_property
    def identity(self) -> str:
        """Stable correlation only: never rewrite existing IDs or notification keys.

        Include the physical row kind: equal keys in the two legacy tables are
        not evidence of equal conditions. Membership/handling do not affect it.
        A missing condition key falls back to the exact legacy row.
        """
        payload = [
            self.tenant_id,
            self.row_kind,
            self.type_name,
            self.condition_key or f"row:{self.row_id}",
        ]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    @cached_property
    def participant_set(self) -> frozenset[Participant]:
        return frozenset(self.participants)

    @cached_property
    def has_independent_software_subject(self) -> bool:
        return any(
            p.kind in {"software_product", "software_version"} and p.role == "affected"
            for p in self.participants
        )


@dataclass(frozen=True)
class EvaluationCoverage:
    succeeded: bool
    complete: bool
    fresh: bool
    scope_matches: bool

    @property
    def permits_clearing(self) -> bool:
        return self.succeeded and self.complete and self.fresh and self.scope_matches


@dataclass(frozen=True)
class Signal:
    prerequisite: str
    participant: Participant
    readiness: Readiness
    reason: str
    blocker_references: tuple[str, ...] = ()

    def __post_init__(self):
        if self.readiness not in set(Readiness) or not self.prerequisite or not self.reason:
            raise ValueError("Invalid prerequisite signal")


@dataclass(frozen=True)
class Decision:
    condition_identity: str
    participant: Participant | None
    disposition: str
    may_evaluate: bool
    may_notify: bool
    may_execute: bool
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    # These flags are only proposed dependency eligibility, never authorization.
    # Permission, source-action checks and notification routing remain required.
