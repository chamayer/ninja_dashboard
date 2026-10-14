"""Decision helper display and the editable required signals."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.core import software_policy, software_review
from apps.core.models import SoftwareSuggestionRule

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (_ROOT / "apps" / "core" / "migrations" / "0292_software_routine_helper.py").read_text(
    encoding="utf-8"
)


def test_evidence_is_shown_in_plain_words_and_unknown_codes_are_readable():
    details = {"evidence": ["known_vendor", "established_publisher", "new_thing", 7]}
    assert software_review.evidence_labels(details) == [
        "known vendor",
        "established publisher",
        "new thing",
    ]
    assert software_review.evidence_labels({}) == []


def test_a_group_of_routine_titles_is_labeled_routine():
    row = (
        "f1",
        "whitelist_suggestion",
        "low",
        {
            "canonical_name": "Foo",
            "publisher": "Acme",
            "fleet_device_count": 9,
            "suggestion": "supports_approval",
            "evidence": ["known_vendor"],
        },
        None,
        "global",
    )
    (group,) = software_review.build_groups([row])
    assert group["suggestion"] == "supports_approval"
    assert group["titles"][0]["evidence"] == ["known vendor"]


def test_choices_include_the_new_signals_and_suggestion():
    assert "known_vendor" in SoftwareSuggestionRule.Signal.values
    assert "publisher_approved" in SoftwareSuggestionRule.Signal.values
    assert "supports_approval" in SoftwareSuggestionRule.Suggestion.values


def _rule(signal="known_vendor"):
    saved = []
    rule = SimpleNamespace(
        id=1, priority=55, signal=signal, adverse=False, suggestion="supports_approval",
        enabled=True, requires=[], save=lambda update_fields: saved.append(update_fields),
    )
    return rule, saved


def _update(monkeypatch, rule, post):
    monkeypatch.setattr(software_policy, "get_object_or_404", lambda *_a, **_k: rule)
    monkeypatch.setattr(software_policy, "_audit", lambda *_a, **_k: None)
    request = SimpleNamespace(POST={"rule_id": "1", "priority": "55", **post})
    return software_policy._update_suggestion(request)


def test_required_signals_are_validated_and_saved(monkeypatch):
    rule, saved = _rule()
    assert _update(monkeypatch, rule, {"suggestion": "supports_approval", "requires": "established_publisher, prevalent"}) == ""
    assert rule.requires == ["established_publisher", "prevalent"]
    assert "requires" in saved[0]


def test_unknown_or_self_required_signal_is_refused(monkeypatch):
    rule, _ = _rule()
    assert "Unknown required signal" in _update(
        monkeypatch, rule, {"suggestion": "supports_approval", "requires": "made_up"}
    )
    assert "cannot require its own" in _update(
        monkeypatch, rule, {"suggestion": "supports_approval", "requires": "known_vendor"}
    )


def test_migration_adds_the_helper_rules_and_disables_popularity_rules():
    assert "'supports_approval'" in _MIGRATION
    assert '"established_publisher"' in _MIGRATION
    assert "SET enabled = FALSE" in _MIGRATION
    assert "'established_publisher', 'prevalent'" in _MIGRATION
    assert "0291_finding_type_alertable" in _MIGRATION


def test_review_page_survives_a_finding_with_no_title():
    template = (_ROOT / "templates" / "software_decisions.html").read_text(encoding="utf-8")
    assert "{% if t.title %}<a href=\"{% url 'software_detail' name=t.title %}\">" in template
    assert "(no title recorded)" in template


def test_review_groups_read_details_that_arrive_as_json_text():
    # Django's raw cursor returns jsonb as text; this is what production sends.
    details = (
        '{"canonical_name": "Foo", "publisher": "Acme", "fleet_device_count": 9, '
        '"suggestion": "supports_approval", "evidence": ["known_vendor"]}'
    )
    (group,) = software_review.build_groups(
        [("f1", "whitelist_suggestion", "low", details, None, "global")]
    )
    assert group["titles"][0]["title"] == "Foo"
    assert group["titles"][0]["devices"] == 9
    assert group["titles"][0]["evidence"] == ["known vendor"]
    assert software_review._details("not json") == {}
    assert software_review._details("[1]") == {}
