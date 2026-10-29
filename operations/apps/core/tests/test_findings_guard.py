"""Findings writers take the exclusive tenant guard and declare contract 4 (PLAN-003 R2)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from shared import findings_contract
from shared.findings_contract import FINDING_CONTRACT, guard_findings_writes

from apps.core import findings_guard

VIEWS = Path("apps/core/views.py").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = VIEWS.index(f"\ndef {name}(")
    end = VIEWS.find("\ndef ", start + 5)
    return VIEWS[start:end]


def test_guard_declares_tenant_and_contract_then_takes_the_exclusive_guard():
    cursor = mock.Mock()
    guard_findings_writes(cursor, 1)
    first, second = cursor.execute.call_args_list
    assert "set_config('operations.tenant_id'" in first.args[0]
    assert "set_config('operations.finding_contract'" in first.args[0]
    assert first.args[1] == ("1", str(FINDING_CONTRACT))
    assert second.args == ("SELECT operations.acquire_tenant_guard(%s, 'exclusive')", (1,))


def test_operations_guard_uses_the_request_connection():
    cursor = mock.MagicMock()
    with mock.patch.object(findings_guard.connection, "cursor", return_value=cursor):
        findings_guard.guard_findings()
    entered = cursor.__enter__.return_value
    assert entered.execute.call_count == 2


@pytest.mark.parametrize(
    "handler",
    [
        "finding_acknowledge",
        "finding_resolve",
        "finding_snooze",
        "finding_suppress",
        "findings_bulk_action",
        "admin_finding_acknowledge",
        "admin_finding_apply_client_rename",
        "client_candidate_accept",
        "client_candidate_map",
        "merge_candidate_group_review",
        "device_merge",
        "computer_merge_split",
        "software_decision_bulk",
        "software_decision_create",
    ],
)
def test_every_findings_writing_handler_takes_the_guard(handler):
    assert "guard_findings()" in _body(handler)


def test_refused_requests_take_no_guard():
    bulk = _body("findings_bulk_action")
    assert bulk.index("raise PermissionDenied") < bulk.index("guard_findings()")
    split = _body("computer_merge_split")
    assert split.index("A reason is required") < split.index("guard_findings()")
    for handler in ("merge_candidate_group_review", "device_merge"):
        body = _body(handler)
        assert body.index('if request.method == "POST":') < body.index("guard_findings()")


def test_admin_findings_are_written_through_the_common_ledger():
    assert "UPDATE operations.admin_findings" not in VIEWS
    assert '.save(update_fields=["status", "resolved_at"])' not in VIEWS
    assert "condition_namespace = 'admin'" in _body("admin_finding_acknowledge")


def test_contract_command_refuses_a_mismatched_database():
    with (
        mock.patch(
            "apps.core.management.commands.check_findings_contract.database_findings_contract",
            return_value=FINDING_CONTRACT - 1,
        ),
        mock.patch("apps.core.management.commands.check_findings_contract.connection"),
    ):
        with pytest.raises(CommandError, match="findings contract"):
            call_command("check_findings_contract")


def test_database_contract_is_none_before_publication():
    cursor = mock.Mock()
    cursor.fetchone.return_value = (False,)
    assert findings_contract.database_findings_contract(cursor) is None
