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
    "A comment is required. Approves the whole publisher; a title with another concern still shows.",
)
SOFTWARE_REJECT = _software_action(
    "software_reject",
    "Reject software",
    "Reject the selected software titles? Installed copies will raise an issue.",
    "A comment is required. Rejected software that is installed raises its own issue.",
)
SOFTWARE_REJECT_PUBLISHER = _software_action(
    "software_reject_publisher",
    "Reject publisher",
    "Reject EVERY title from the publishers of the selected software? Each installed copy raises an issue.",
    "A comment is required. Rejects the whole publisher; a title with its own decision keeps it.",
)
SOFTWARE_INVESTIGATE_PUBLISHER = _software_action(
    "software_investigate_publisher",
    "Investigate publisher",
    "Mark the publishers of the selected software as being investigated?",
    "A comment is required.",
)
SOFTWARE_INVESTIGATE = _software_action(
    "software_investigate",
    "Investigate",
    "Mark the selected software titles as being investigated?",
    "",
)

# A curator judges whether a product really has a candidate capability.
CURATE_CAPABILITY_PERMISSION = "operations.curate_software_capability"

CAPABILITY_CONFIRM = FindingAction(
    key="capability_confirm",
    label="Confirm capability",
    permission=CURATE_CAPABILITY_PERMISSION,
    finding_types=frozenset({"capability_review_candidate"}),
    requires_reason=False,
    confirmation="Confirm the selected products have this capability? This is a global decision.",
    eligibility_hint="Records the capability as true for each selected product and closes the issue.",
)

CAPABILITY_REJECT = FindingAction(
    key="capability_reject",
    label="Reject capability",
    permission=CURATE_CAPABILITY_PERMISSION,
    finding_types=frozenset({"capability_review_candidate"}),
    requires_reason=False,
    confirmation="Reject this capability for the selected products? This is a global decision.",
    eligibility_hint="Records the capability as not true for each selected product and closes the issue.",
)

# Computer identity (ADR-0032): each runs a recorded database operation.
MERGE_COMPUTERS = FindingAction(
    key="merge_computers",
    label="Merge these Computers",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"duplicate_device_records"}),
    requires_reason=True,
    confirmation=(
        "Merge the Computers each selected issue names into one? "
        "Each merge is recorded and can be split again."
    ),
    eligibility_hint=(
        "Not available when an issue names Computers proven to be different machines."
    ),
)

CONFIRM_COMPUTERS_SEPARATE = FindingAction(
    key="confirm_computers_separate",
    label="Confirm separate machines",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"duplicate_device_records", "identity_conflict", "shared_serial"}),
    requires_reason=True,
    confirmation=(
        "Record that the Computers each selected issue names are different machines? "
        "They will not be proposed as duplicates or merged automatically again."
    ),
    eligibility_hint="Records an operator decision on each named Computer.",
)

SPLIT_COMPUTER_RECORDS = FindingAction(
    key="split_computer_records",
    label="Split as proposed",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"two_machines_on_one_computer"}),
    requires_reason=True,
    confirmation=(
        "Split the proposed records off each selected Computer? They are matched again, "
        "never to that Computer."
    ),
    eligibility_hint="The issue shows which machine stays and which records move.",
)

CONFIRM_COMPUTERS_IN_USE = FindingAction(
    key="confirm_computers_in_use",
    label="Still in use",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"device_missing_from_source"}),
    requires_reason=True,
    confirmation=(
        "Confirm the selected Computers are still in use? Each missing required agent "
        "will be reported, and they will not be retired automatically."
    ),
    eligibility_hint="Clears itself when the machine reports again.",
)

# A Computer linked to more than one client (ADR-0040).
MOVE_COMPUTER_CLIENT = FindingAction(
    key="move_computer_client",
    label="Move to the other client",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"computer_client_conflict"}),
    requires_reason=True,
    confirmation=(
        "Move each selected Computer, with its issues and software, to the client its "
        "evidence names? Records still filed under the old client are listed again."
    ),
    eligibility_hint="Available when an issue's evidence names exactly one other client.",
)

KEEP_COMPUTER_CLIENT = FindingAction(
    key="keep_computer_client",
    label="Keep as is",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"computer_client_conflict"}),
    requires_reason=True,
    confirmation=(
        "Keep each selected Computer where it is? Use this when the other client is "
        "intended, or the matching serial belongs to a different machine. New evidence "
        "raises the issue again."
    ),
    eligibility_hint="Records the decision for the evidence shown now.",
)

COMPUTER_CLIENT_SOURCE_WRONG = FindingAction(
    key="computer_client_source_wrong",
    label="Source is wrong",
    permission=LIFECYCLE_PERMISSION,
    finding_types=frozenset({"computer_client_conflict"}),
    requires_reason=True,
    confirmation=(
        "Mark each selected issue as a source filing error? It stays acknowledged until the "
        "source is corrected, then clears."
    ),
    eligibility_hint="Correct the client in the source; the issue clears on the next run.",
)

IDENTITY_ACTIONS = frozenset(
    {
        MERGE_COMPUTERS.key,
        CONFIRM_COMPUTERS_SEPARATE.key,
        SPLIT_COMPUTER_RECORDS.key,
        CONFIRM_COMPUTERS_IN_USE.key,
        MOVE_COMPUTER_CLIENT.key,
        KEEP_COMPUTER_CLIENT.key,
        COMPUTER_CLIENT_SOURCE_WRONG.key,
    }
)

FINDING_ACTIONS = {
    BULK_RETIRE_COMPUTERS.key: BULK_RETIRE_COMPUTERS,
    MERGE_COMPUTERS.key: MERGE_COMPUTERS,
    CONFIRM_COMPUTERS_SEPARATE.key: CONFIRM_COMPUTERS_SEPARATE,
    SPLIT_COMPUTER_RECORDS.key: SPLIT_COMPUTER_RECORDS,
    CONFIRM_COMPUTERS_IN_USE.key: CONFIRM_COMPUTERS_IN_USE,
    MOVE_COMPUTER_CLIENT.key: MOVE_COMPUTER_CLIENT,
    KEEP_COMPUTER_CLIENT.key: KEEP_COMPUTER_CLIENT,
    COMPUTER_CLIENT_SOURCE_WRONG.key: COMPUTER_CLIENT_SOURCE_WRONG,
    ARCHIVE_HUDU_ASSETS.key: ARCHIVE_HUDU_ASSETS,
    APPROVE_REMOTE_ACCESS_ALL.key: APPROVE_REMOTE_ACCESS_ALL,
    APPROVE_REMOTE_ACCESS_CLIENT.key: APPROVE_REMOTE_ACCESS_CLIENT,
    SOFTWARE_APPROVE_TITLE.key: SOFTWARE_APPROVE_TITLE,
    SOFTWARE_APPROVE_PUBLISHER.key: SOFTWARE_APPROVE_PUBLISHER,
    SOFTWARE_REJECT.key: SOFTWARE_REJECT,
    SOFTWARE_REJECT_PUBLISHER.key: SOFTWARE_REJECT_PUBLISHER,
    SOFTWARE_INVESTIGATE_PUBLISHER.key: SOFTWARE_INVESTIGATE_PUBLISHER,
    SOFTWARE_INVESTIGATE.key: SOFTWARE_INVESTIGATE,
    CAPABILITY_CONFIRM.key: CAPABILITY_CONFIRM,
    CAPABILITY_REJECT.key: CAPABILITY_REJECT,
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
