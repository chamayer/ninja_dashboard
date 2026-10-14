"""Approve remote access from the Issues queue: separate from software approval."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from apps.core import finding_actions, remote_access_approval


def _finding(client_id, details):
    return SimpleNamespace(client_id=client_id, finding_details=details)


def test_two_actions_registered_for_remote_access_only_and_gated_by_authorization():
    for action in (
        finding_actions.APPROVE_REMOTE_ACCESS_ALL,
        finding_actions.APPROVE_REMOTE_ACCESS_CLIENT,
    ):
        assert action.finding_types == frozenset({"unauthorized_remote_access"})
        assert action.permission == "operations.authorize_software_product"
        assert action.requires_reason
        assert finding_actions.FINDING_ACTIONS[action.key] is action


def test_all_clients_collapses_to_one_approval_per_product():
    product = uuid.uuid4()
    details = {"product_uuid": str(product), "capability": "remote_access"}
    findings = [_finding(uuid.uuid4(), details), _finding(uuid.uuid4(), details)]
    assert remote_access_approval._targets(findings, True) == {(None, product, "remote_access")}


def test_client_scope_approves_each_selected_client_separately():
    product, one, two = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    details = {"product_uuid": str(product), "capability": "remote_access"}
    findings = [_finding(one, details), _finding(two, details), _finding(one, details)]
    assert remote_access_approval._targets(findings, False) == {
        (one, product, "remote_access"),
        (two, product, "remote_access"),
    }


@pytest.mark.parametrize(
    "client,details",
    [
        (uuid.uuid4(), {"capability": "remote_access"}),
        (uuid.uuid4(), {"product_uuid": "not-a-uuid", "capability": "remote_access"}),
        (uuid.uuid4(), {"product_uuid": str(uuid.uuid4())}),
        (None, {"product_uuid": str(uuid.uuid4()), "capability": "remote_access"}),
    ],
)
def test_incomplete_selection_is_refused(client, details):
    with pytest.raises(ValueError):
        remote_access_approval._targets([_finding(client, details)], False)


def test_approval_writes_only_authorization_never_software_decision():
    source = open(remote_access_approval.__file__, encoding="utf-8").read()
    assert "SoftwareDecision" not in source
    assert "ProductAuthorization.objects.create" in source
    assert "withdrawn_reason" in source  # older decision is kept, not overwritten
