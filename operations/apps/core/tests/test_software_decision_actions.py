"""Decide undecided software from the Issues queue."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.core import finding_actions, software_decision_actions
from apps.core.models import SoftwareDecision

_SOURCE = Path(software_decision_actions.__file__).read_text(encoding="utf-8")


def _finding(**details):
    return SimpleNamespace(finding_details=details)


def test_four_actions_registered_on_undecided_software_only():
    keys = {
        "software_approve_title",
        "software_approve_publisher",
        "software_reject",
        "software_investigate",
    }
    for key in keys:
        assert software_decision_actions.decision_for(key) is not None
        action = finding_actions.FINDING_ACTIONS[key]
        assert action.finding_types == frozenset({"rare_recent", "whitelist_suggestion"})
        assert not action.requires_reason


def test_decisions_map_to_the_review_page_vocabulary():
    d = software_decision_actions.decision_for
    assert d("software_approve_title") == (SoftwareDecision.Decision.APPROVE, False)
    assert d("software_approve_publisher") == (SoftwareDecision.Decision.APPROVE_PUBLISHER, True)
    assert d("software_reject")[0] == SoftwareDecision.Decision.REJECT
    assert d("software_investigate")[0] == SoftwareDecision.Decision.INVESTIGATE
    assert d("not_an_action") is None


def test_titles_dedupe_case_insensitively_and_blank_values_are_counted():
    findings = [
        _finding(canonical_name="Foo Tool", publisher="Acme"),
        _finding(canonical_name="foo tool", publisher="Acme"),
        _finding(canonical_name="", publisher="Acme"),
    ]
    keys, skipped = software_decision_actions.match_values(findings, by_publisher=False)
    assert keys == {"foo tool": "Foo Tool"}
    assert skipped == 1
    keys, skipped = software_decision_actions.match_values(findings, by_publisher=True)
    assert keys == {"acme": "Acme"} and skipped == 0


def test_login_only_actions_do_not_need_a_permission_but_others_do():
    anon = SimpleNamespace(is_authenticated=False)
    user = SimpleNamespace(is_authenticated=True, is_superuser=False, has_perm=lambda _p: False)
    approve = finding_actions.SOFTWARE_APPROVE_TITLE
    assert not finding_actions.can_run_action(anon, approve)
    assert finding_actions.can_run_action(user, approve)
    assert not finding_actions.can_run_action(user, finding_actions.APPROVE_REMOTE_ACCESS_ALL)


def test_decision_is_global_audited_and_never_writes_remote_access():
    assert "client=None" in _SOURCE and "device=None" in _SOURCE
    assert '"software_decision.set"' in _SOURCE
    assert "resolve_decided_prompts" in _SOURCE
    assert "ProductAuthorization" not in _SOURCE
