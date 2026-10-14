"""Confirm or reject a candidate capability from the Issues queue."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.core import capability_review_actions as actions
from apps.core import finding_actions

_SOURCE = Path(actions.__file__).read_text(encoding="utf-8")


def _finding(**details):
    return SimpleNamespace(finding_details=details)


def test_actions_registered_for_capability_review_only_and_gated_by_the_curator_permission():
    for action in (finding_actions.CAPABILITY_CONFIRM, finding_actions.CAPABILITY_REJECT):
        assert action.finding_types == frozenset({"capability_review_candidate"})
        assert action.permission == "operations.curate_software_capability"
        assert finding_actions.FINDING_ACTIONS[action.key] is action


def test_distinct_product_and_capability_pairs_are_collected():
    product = uuid.uuid4()
    findings = [
        _finding(product_uuid=str(product), capability="remote_access"),
        _finding(product_uuid=str(product), capability="remote_access"),
        _finding(product_uuid=str(product), capability="rmm"),
    ]
    assert actions.targets(findings) == {(product, "remote_access"), (product, "rmm")}


@pytest.mark.parametrize(
    "details",
    [{"capability": "rmm"}, {"product_uuid": "nope", "capability": "rmm"}, {"product_uuid": str(uuid.uuid4())}],
)
def test_incomplete_selection_is_refused(details):
    with pytest.raises(ValueError):
        actions.targets([_finding(**details)])


def test_decision_is_recorded_audited_and_the_findings_are_closed_with_a_reason():
    assert "capability_evidence.confirm(" in _SOURCE
    assert '"software_capability.confirm" if confirm else "software_capability.reject"' in _SOURCE
    assert "SET status = 'resolved'" in _SOURCE
    assert '"reason": "capability_decided"' in _SOURCE
    assert "resolved_by" in _SOURCE and "resolved_at" in _SOURCE
