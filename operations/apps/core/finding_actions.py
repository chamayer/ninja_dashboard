"""Registered operator actions initiated from Findings.

Findings state derived facts.  A registered action is an explicit operator
operation, with its own permission and eligibility boundary.  This small
registry is intentionally local to Operations: a future source API action must
add its own capability check and confirmation contract rather than treating a
Finding as permission to mutate a source.
"""

from __future__ import annotations

from dataclasses import dataclass

LIFECYCLE_PERMISSION = "operations.manage_lifecycle"


@dataclass(frozen=True)
class FindingAction:
    key: str
    label: str
    permission: str
    finding_types: frozenset[str]
    requires_reason: bool = False
    confirmation: str = ""
    eligibility_hint: str = ""


BULK_RETIRE_COMPUTERS = FindingAction(
    key="retire_computers",
    label="Retire eligible Computers",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"device_missing_from_source"}),
    requires_reason=True,
    confirmation="Retire the selected eligible Computers? Source records and history will be kept.",
    eligibility_hint=(
        "Retirement is available only for selected “No current source record” "
        "issues whose Computers still need review."
    ),
)

ARCHIVE_HUDU_ASSETS = FindingAction(
    key="archive_hudu_assets",
    label="Archive in Hudu",
    permission="operations.manage_sources",
    finding_types=frozenset({"cmdb_asset_stale"}),
    requires_reason=True,
    confirmation=(
        "Queue Archive in Hudu for the selected eligible records? "
        "Each target will be checked again before it is sent to Hudu."
    ),
    eligibility_hint=(
        "Available only for current Hudu records with linked external records "
        "that no longer resolve in their source. Unlinked Hudu records are excluded."
    ),
)


FINDING_ACTIONS = {
    BULK_RETIRE_COMPUTERS.key: BULK_RETIRE_COMPUTERS,
    ARCHIVE_HUDU_ASSETS.key: ARCHIVE_HUDU_ASSETS,
}


def can_manage_lifecycle(user: object) -> bool:
    """Return whether ``user`` can change canonical Computer lifecycle."""
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "has_perm", lambda _permission: False)(LIFECYCLE_PERMISSION)
    )


def available_finding_actions(user: object) -> tuple[FindingAction, ...]:
    """Actions this operator is authorized to start from the Findings page."""
    return tuple(
        action
        for action in FINDING_ACTIONS.values()
        if getattr(user, "is_superuser", False)
        or getattr(user, "has_perm", lambda _permission: False)(action.permission)
    )
