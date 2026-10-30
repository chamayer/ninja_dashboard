"""Rule results for managed source records (PLAN-004 R4 Stage A); no database."""

from __future__ import annotations

import uuid

import pytest

from ingest import normalize, source_records


@pytest.fixture(autouse=True)
def _rejections(monkeypatch):
    monkeypatch.setattr(
        normalize, "_serial_rejection_cache", frozenset({"to be filled by o.e.m."})
    )


def _record(**overrides):
    record = {
        "id": uuid.uuid4(),
        "record_role": "endpoint_agent",
        "presence": "present",
        "entity_type": "agent.rmm",
        "canonical_data": {"serial_number": "ABC12345", "hostname": "pc1"},
        "device_id": None,
        "device_live": False,
        "match_method": None,
        "restricted": False,
        "candidate_pending": False,
    }
    record.update(overrides)
    return record


def _by_rule(results):
    return {(r["rule"], r["dimension"]): r for r in results}


def test_unattached_record_with_two_candidates_needs_identity_review():
    two = {uuid.uuid4(): {"serial"}, uuid.uuid4(): {"name"}}
    result = _by_rule(source_records.evaluate_record(_record(), two))[
        ("identity.association", "")
    ]
    assert result["result"] == "contradicted"
    assert result["finding"]["severity"] == "critical"


def test_pending_candidate_owns_identity_work():
    two = {uuid.uuid4(): {"serial"}, uuid.uuid4(): {"mac"}}
    result = _by_rule(
        source_records.evaluate_record(_record(candidate_pending=True), two)
    )[("identity.association", "")]
    assert result["result"] == "contradicted"
    assert result["owner"] == "entity_candidate"
    assert result["finding"] is None


def test_single_candidate_is_unknown_not_an_issue():
    result = _by_rule(
        source_records.evaluate_record(_record(), {uuid.uuid4(): {"name"}})
    )[("identity.association", "")]
    assert result["result"] == "unknown"
    assert result["finding"] is None


def test_placeholder_serial_on_attached_record_belongs_to_legacy_finding():
    record = _record(
        device_id=uuid.uuid4(),
        device_live=True,
        canonical_data={"serial_number": "To be filled by O.E.M."},
    )
    result = _by_rule(source_records.evaluate_record(record, {}))[
        ("identifier.validity", "serial")
    ]
    assert result["result"] == "contradicted"
    assert result["owner"] == "legacy:placeholder_serial"
    assert result["finding"] is None


def test_missing_serial_is_unknown_and_documentation_is_not_applicable():
    missing = _by_rule(source_records.evaluate_record(_record(canonical_data={}), {}))
    assert missing[("identifier.validity", "serial")]["result"] == "unknown"
    docs = _by_rule(
        source_records.evaluate_record(_record(record_role="documentation"), {})
    )
    assert docs[("identity.association", "")]["result"] == "not_applicable"


def test_unclassified_role_is_unknown_for_role_rule():
    results = _by_rule(
        source_records.evaluate_record(_record(record_role="unclassified"), {})
    )
    assert results[("record.role", "")]["missing"] == ["record_role"]
