"""One comment rule and one vocabulary for every software decision."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.core import finding_actions, software_decision_actions, software_decision_rules
from apps.core.models import SoftwareDecision
from apps.core.templatetags import human_labels

_ROOT = Path(__file__).resolve().parents[3]
_VIEWS = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
_TEMPLATES = _ROOT / "templates"


@pytest.mark.parametrize(
    ("decision", "publisher_level", "required"),
    [
        ("approve", False, False),
        ("investigate", False, False),
        ("reject", False, True),
        ("approve_publisher", True, True),
        ("approve", True, True),
        ("investigate", True, True),
        ("reject", True, True),
    ],
)
def test_high_effect_decisions_need_a_comment(decision, publisher_level, required):
    problem = software_decision_rules.comment_problem(
        decision, publisher_level=publisher_level, comment="  "
    )
    assert bool(problem) is required
    assert not software_decision_rules.comment_problem(
        decision, publisher_level=publisher_level, comment="Reviewed with the client"
    )


def test_a_comment_cannot_be_longer_than_the_limit():
    long = "x" * (software_decision_rules.COMMENT_MAX_LENGTH + 1)
    assert "characters" in software_decision_rules.comment_problem(
        "approve", publisher_level=False, comment=long
    )


def test_every_handler_that_records_a_decision_applies_the_rule():
    # create, bulk and the client page, plus the Issues bar.
    assert _VIEWS.count("software_decision_rules.comment_problem(") == 3
    actions = Path(software_decision_actions.__file__).read_text(encoding="utf-8")
    assert "software_decision_rules.comment_problem(" in actions
    assert '"reason": reason,' in _VIEWS


def test_publisher_reject_and_investigate_are_queue_actions_with_the_same_handler():
    for key, decision in (
        ("software_reject_publisher", SoftwareDecision.Decision.REJECT),
        ("software_investigate_publisher", SoftwareDecision.Decision.INVESTIGATE),
    ):
        assert software_decision_actions.decision_for(key) == (decision, True)
        action = finding_actions.FINDING_ACTIONS[key]
        assert action.finding_types == frozenset({"rare_recent", "whitelist_suggestion"})
        assert "comment is required" in action.eligibility_hint.lower()
    assert "EVERY title" in finding_actions.SOFTWARE_REJECT_PUBLISHER.confirmation


def test_vocabulary_is_approve_reject_investigate_everywhere():
    labels = human_labels.__dict__
    source = Path(human_labels.__file__).read_text(encoding="utf-8")
    for old in ('"approve": "Allow"', '"reject": "Block"', '"approve_publisher": "Trust publisher"'):
        assert old not in source
    assert '"approve": "Approved"' in source and '"reject": "Rejected"' in source
    assert labels
    for template in ("software_products.html", "software_decision_log.html", "software_page.html"):
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        assert ">Allowed<" not in text and ">Blocked<" not in text and "allow or block" not in text


def test_every_page_that_records_a_decision_collects_the_comment():
    for template in (
        "org_software.html",
        "software_detail.html",
        "software_products.html",
        "software_publishers.html",
        "software_publisher_detail.html",
        "software_decisions.html",
    ):
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        assert '{% include "_decision_comment_script.html" %}' in text, template


def test_products_list_matches_decisions_ignoring_case_and_shows_the_main_publisher():
    assert "sd.canonical_name = sic.canonical_name" not in _VIEWS
    assert _VIEWS.count("LOWER(sd.canonical_name) = LOWER(sic.canonical_name)") == 4
    assert "ORDER BY COUNT(*) DESC, installed.publisher" in _VIEWS
