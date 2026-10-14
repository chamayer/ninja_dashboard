"""Decision helper: "Supports approval" needs several agreeing facts, never popularity alone."""

from __future__ import annotations

import pytest

from ingest.software_reconcile import suggestion_for, vendor_key

RULES = [
    (10, "threat_hit", True, "investigate"),
    (40, "unauthorized_capability", True, "review_capability"),
    (52, "publisher_approved", False, "supports_approval", []),
    (55, "known_vendor", False, "supports_approval", ["established_publisher"]),
    (60, "established_publisher", False, "approve_publisher"),
    (80, "fallback", False, "none"),
]


@pytest.mark.parametrize(
    ("publisher", "key"),
    [
        ("Microsoft Corporation", "microsoft"),
        ("Adobe Inc.", "adobe"),
        ("The Document Foundation", "document_foundation"),
        ("Mozilla", "mozilla"),
        ("", ""),
        (None, ""),
    ],
)
def test_vendor_key_drops_legal_forms_and_punctuation(publisher, key):
    assert vendor_key(publisher) == key


def test_known_vendor_alone_is_not_enough():
    assert suggestion_for(RULES, {"known_vendor"}) == "none"


def test_known_vendor_with_established_use_supports_approval():
    assert suggestion_for(RULES, {"known_vendor", "established_publisher"}) == "supports_approval"


def test_publisher_already_approved_supports_approval_on_its_own():
    assert suggestion_for(RULES, {"publisher_approved"}) == "supports_approval"


def test_popularity_alone_gives_no_approve_when_those_rules_are_absent():
    assert suggestion_for(RULES[:-2] + RULES[-1:], {"prevalent"}) == "none"


def test_a_warning_sign_always_beats_routine():
    signals = {"known_vendor", "established_publisher", "publisher_approved", "threat_hit"}
    assert suggestion_for(RULES, signals) == "investigate"


def test_four_tuple_rules_still_work():
    assert suggestion_for([(10, "threat_hit", True, "investigate")], {"threat_hit"}) == "investigate"


def test_supporting_facts_are_kept_apart_from_warning_signals():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "software_reconcile.py").read_text(encoding="utf-8")
    assert '"evidence": sorted(signals & supporting)' in source
    assert '"signals": sorted(signals - supporting)' in source
