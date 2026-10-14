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


# Remote access is approved on its own, apart from software approval. Two
# buttons make the scope explicit: the MSP's own management tool is approved for
# every client; any other tool is approved for the clients of the selected issues.
AUTHORIZE_SOFTWARE_PERMISSION = "operations.authorize_software_product"

APPROVE_REMOTE_ACCESS_ALL = FindingAction(
    key="approve_remote_access_all",
    label="Approve remote access: all clients",
    permission=AUTHORIZE_SOFTWARE_PERMISSION,
    finding_types=frozenset({"unauthorized_remote_access"}),
    requires_reason=True,
    confirmation=(
        "Approve the selected remote access tools for ALL clients? "
        "Use this only for the management tool you run for every client."
    ),
    eligibility_hint=(
        "Approves the product on the selected issues, everywhere. Software approval is not changed."
    ),
)

APPROVE_REMOTE_ACCESS_CLIENT = FindingAction(
    key="approve_remote_access_client",
    label="Approve remote access: these clients",
    permission=AUTHORIZE_SOFTWARE_PERMISSION,
    finding_types=frozenset({"unauthorized_remote_access"}),
    requires_reason=True,
    confirmation="Approve the selected remote access tools for the clients of the selected issues?",
    eligibility_hint=(
        "Approves each selected product only at the client of each selected issue."
    ),
)


# Undecided software is decided from the queue. Anyone who can use the review
# page can decide, so these carry no extra permission (empty string).
_SOFTWARE_PROMPTS = frozenset({"rare_recent", "whitelist_suggestion"})


def _software_action(key: str, label: str, confirmation: str, hint: str) -> FindingAction:
    return FindingAction(
        key=key,
        label=label,
        permission="",
        finding_types=_SOFTWARE_PROMPTS,
        requires_reason=False,
        confirmation=confirmation,
        eligibility_hint=hint,
    )


SOFTWARE_APPROVE_TITLE = _software_action(
    "software_approve_title",
    "Approve software",
    "Approve the selected software titles everywhere?",
    "Approves each selected title for every client. Remote access is approved separately.",
)
SOFTWARE_APPROVE_PUBLISHER = _software_action(
    "software_approve_publisher",
    "Approve publisher",
    "Approve the publishers of the selected software for every title they make?",
    "Approves the whole publisher; a title with another concern still shows.",
)
SOFTWARE_REJECT = _software_action(
    "software_reject",
    "Reject software",
    "Reject the selected software titles? Installed copies will raise an issue.",
    "Rejected software that is installed raises its own issue.",
)
SOFTWARE_INVESTIGATE = _software_action(
    "software_investigate",
    "Investigate",
    "Mark the selected software titles as being investigated?",
    "",
)

FINDING_ACTIONS = {
    BULK_RETIRE_COMPUTERS.key: BULK_RETIRE_COMPUTERS,
    ARCHIVE_HUDU_ASSETS.key: ARCHIVE_HUDU_ASSETS,
    APPROVE_REMOTE_ACCESS_ALL.key: APPROVE_REMOTE_ACCESS_ALL,
    APPROVE_REMOTE_ACCESS_CLIENT.key: APPROVE_REMOTE_ACCESS_CLIENT,
    SOFTWARE_APPROVE_TITLE.key: SOFTWARE_APPROVE_TITLE,
    SOFTWARE_APPROVE_PUBLISHER.key: SOFTWARE_APPROVE_PUBLISHER,
    SOFTWARE_REJECT.key: SOFTWARE_REJECT,
    SOFTWARE_INVESTIGATE.key: SOFTWARE_INVESTIGATE,
}


def can_run_action(user: object, action: FindingAction) -> bool:
    """Whether ``user`` may start ``action``; an empty permission needs only a login."""
    if not action.permission:
        return bool(getattr(user, "is_authenticated", False))
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "has_perm", lambda _permission: False)(action.permission)
    )


def can_manage_lifecycle(user: object) -> bool:
    """Return whether ``user`` can change canonical Computer lifecycle."""
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "has_perm", lambda _permission: False)(LIFECYCLE_PERMISSION)
    )


def available_finding_actions(user: object) -> tuple[FindingAction, ...]:
    """Actions this operator is authorized to start from the Findings page."""
    return tuple(action for action in FINDING_ACTIONS.values() if can_run_action(user, action))
