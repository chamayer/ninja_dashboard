"""Rule results for managed source records (PLAN-004 R4 Stage A); no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
        "platform": "Ninja",
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
    result = _by_rule(
        source_records.evaluate_record(_record(), two, identity_conflicts=two)
    )[("identity.association", "")]
    assert result["result"] == "contradicted"
    assert result["finding"]["severity"] == "critical"


def test_weak_name_candidates_are_unknown_without_a_qualified_conflict():
    two = {uuid.uuid4(): {"name"}, uuid.uuid4(): {"name"}}
    result = _by_rule(source_records.evaluate_record(_record(), two))[
        ("identity.association", "")
    ]
    assert result["result"] == "unknown"
    assert result["finding"] is None


def test_agent_status_and_contact_are_assessed_independently():
    contact = datetime(2026, 10, 29, 12, tzinfo=UTC)
    results = _by_rule(
        source_records.evaluate_record(
            _record(reported_online=False, reported_last_contact_at=contact), {}
        )
    )
    status = results[("record.reported_status", "connectivity")]
    last_contact = results[("record.reported_contact", "last_contact")]
    assert status["result"] == "supported"
    assert status["evidence"] == {"reported_online": False}
    assert last_contact["result"] == "supported"
    assert last_contact["evidence"]["reported_last_contact_at"].startswith(
        "2026-10-29T12:00:00"
    )
    assert all(result["finding"] is None for result in (status, last_contact))


def test_missing_agent_status_and_contact_are_unknown_not_clean():
    results = _by_rule(source_records.evaluate_record(_record(), {}))
    assert results[("record.reported_status", "connectivity")]["missing"] == [
        "reported_online"
    ]
    assert results[("record.reported_contact", "last_contact")]["missing"] == [
        "reported_last_contact_at"
    ]


def test_source_group_attribution_is_not_inferred_from_record_membership():
    results = _by_rule(
        source_records.evaluate_record(
            _record(
                canonical_data={"platform_group_id": "group-7"},
                # A client can be inherited from the attached Computer; that
                # alone does not prove a source-group mapping exists.
                client_id=uuid.uuid4(),
                device_live=True,
                device_client_id=uuid.uuid4(),
            ),
            {},
        )
    )
    result = results[("record.source_attribution", "")]
    assert result["result"] == "unknown"
    assert result["evidence"] == {"platform_group_id": "group-7"}
    assert result["missing"] == ["source_group_mapping"]
    assert result["owner"] == "source_group_mapping"
    assert result["finding"] is None


def test_settled_source_group_attribution_is_assessed_without_claiming_identity():
    client_id = uuid.uuid4()
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                canonical_data={"platform_group_id": "group-7"},
                source_group_client_id=client_id,
                device_live=True,
                device_client_id=client_id,
            ),
            {},
        )
    )[("record.source_attribution", "")]
    assert result["result"] == "supported"
    assert result["finding"] is None


def test_conflicting_group_and_computer_clients_keep_computer_finding_owner():
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                canonical_data={"platform_group_id": "group-7"},
                source_group_client_id=uuid.uuid4(),
                device_live=True,
                device_client_id=uuid.uuid4(),
            ),
            {},
        )
    )[("record.source_attribution", "")]
    assert result["result"] == "contradicted"
    assert result["owner"] == "legacy:computer_client_conflict"
    assert result["finding"] is None


def test_absent_source_group_is_not_applicable_to_attribution():
    result = _by_rule(source_records.evaluate_record(_record(), {}))[
        ("record.source_attribution", "")
    ]
    assert result["result"] == "not_applicable"


def test_source_record_vulnerability_finding_uses_its_own_inventory():
    risks = [
        {
            "canonical_name": "bad app",
            "version": "1",
            "cve": "CVE-2026-1",
            "cvss": 9.8,
            "kev": True,
        }
    ]
    result = _by_rule(source_records.evaluate_record(_record(), {}, risks))[
        ("software.vulnerability", "")
    ]
    assert result["result"] == "contradicted"
    assert result["finding"]["type"] == "source_record_vulnerable_software"
    assert result["finding"]["severity"] == "critical"
    assert result["evidence"]["installations"][0]["cve"] == "CVE-2026-1"


def test_non_kev_vulnerability_uses_configured_severity():
    risks = [
        {
            "canonical_name": "risky",
            "version": "1",
            "cve": "CVE-2026-2",
            "cvss": 8.0,
            "kev": False,
        }
    ]
    result = _by_rule(
        source_records.evaluate_record(
            _record(), {}, risks, software_severity_high="medium"
        )
    )[("software.vulnerability", "")]
    assert result["finding"]["severity"] == "medium"


def test_explicit_software_rejection_opens_record_finding():
    rejected = [
        {
            "canonical_name": "blocked app",
            "publisher": "Vendor",
            "version": "1",
            "decision": "reject",
        }
    ]
    result = _by_rule(
        source_records.evaluate_record(_record(), {}, rejected_software=rejected)
    )[("software.decision", "")]
    assert result["result"] == "contradicted"
    assert result["finding"]["type"] == "source_record_rejected_software"
    assert result["evidence"]["installations"][0]["canonical_name"] == "blocked app"


def test_missing_software_policy_is_unknown_not_clean():
    result = _by_rule(
        source_records.evaluate_record(_record(), {}, software_policy_known=False)
    )[("software.decision", "")]
    assert result["result"] == "unknown"
    assert result["missing"] == ["client_software_policy"]
    assert result["finding"] is None


def test_unauthorized_capability_opens_source_record_finding():
    tools = [
        {
            "canonical_name": "remote tool",
            "capability": "remote_access",
            "not_permitted_basis": "client deny",
        }
    ]
    result = _by_rule(
        source_records.evaluate_record(_record(), {}, unauthorized_tools=tools)
    )[("software.capability", "")]
    assert result["result"] == "contradicted"
    assert result["finding"]["type"] == "source_record_unauthorized_tool"


def test_missing_capability_policy_or_product_link_is_unknown():
    result = _by_rule(
        source_records.evaluate_record(_record(), {}, capability_policy_known=False)
    )[("software.capability", "")]
    assert result["result"] == "unknown"
    assert result["finding"] is None


def test_source_record_suspicious_name_finding_honors_title_approval():
    subject = uuid.uuid4()

    class Cursor:
        def __init__(self):
            self.results = [
                [("suspicious_name", r"crack", True)],
                [("source_record_suspicious_software", "medium", True)],
                [(subject, "Crack Tool", "Vendor", "1", "", "approve", None, 0, False)],
            ]

        def execute(self, *_args):
            pass

        def fetchall(self):
            return self.results.pop(0)

    found, enabled = source_records._software_signal_findings_by_record(
        Cursor(),
        1,
        [subject],
        {
            "suspicious_name_enabled": True,
            "known_malicious_hint_enabled": True,
            "known_malicious_hint_min_hits": 3,
            "known_malicious_hint_severity": "low",
        },
        {},
    )
    assert enabled == {"suspicious": True, "threat": True}
    assert found == {}


def test_publisher_approval_does_not_hide_suspicious_name_with_another_concern():
    subject = uuid.uuid4()

    class Cursor:
        def __init__(self):
            self.results = [
                [("suspicious_name", r"crack", True)],
                [("source_record_suspicious_software", "medium", True)],
                [
                    (
                        subject,
                        "Crack Tool",
                        "Vendor",
                        "1",
                        "",
                        None,
                        "approve_publisher",
                        1,
                        False,
                    )
                ],
            ]

        def execute(self, *_args):
            pass

        def fetchall(self):
            return self.results.pop(0)

    found, _enabled = source_records._software_signal_findings_by_record(
        Cursor(),
        1,
        [subject],
        {
            "suspicious_name_enabled": True,
            "known_malicious_hint_enabled": True,
            "known_malicious_hint_min_hits": 3,
            "known_malicious_hint_severity": "low",
        },
        {},
    )
    assert found[subject]["suspicious"][0]["severity"] == "medium"


def test_source_record_threat_hint_uses_shared_threshold_and_severity():
    subject = uuid.uuid4()

    class Cursor:
        def __init__(self):
            self.results = [
                [],
                [("source_record_suspicious_software", "medium", True)],
                [(subject, "Unknown App", "Vendor", "1", "", None, None, 3, False)],
            ]

        def execute(self, *_args):
            pass

        def fetchall(self):
            return self.results.pop(0)

    found, _enabled = source_records._software_signal_findings_by_record(
        Cursor(),
        1,
        [subject],
        {
            "suspicious_name_enabled": True,
            "known_malicious_hint_enabled": True,
            "known_malicious_hint_min_hits": 3,
            "known_malicious_hint_severity": "low",
        },
        {},
    )
    assert found[subject]["threat"][0]["threat_hit_count"] == 3
    assert found[subject]["threat"][0]["severity"] == "low"


def test_source_record_software_signal_findings_have_distinct_rules():
    result = _by_rule(
        source_records.evaluate_record(
            _record(),
            {},
            suspicious_software=[
                {
                    "canonical_name": "crack tool",
                    "severity": "medium",
                }
            ],
            malicious_software_hints=[
                {
                    "canonical_name": "unknown app",
                    "severity": "low",
                }
            ],
        )
    )
    assert result[("software.suspicious_name", "")]["finding"]["type"] == (
        "source_record_suspicious_software"
    )
    assert result[("software.threat_intel", "")]["finding"]["type"] == (
        "source_record_malicious_software_hint"
    )


def test_disabled_source_record_software_signals_do_not_resolve_findings():
    result = _by_rule(
        source_records.evaluate_record(
            _record(),
            {},
            suspicious_software_enabled=False,
            malicious_software_enabled=False,
        )
    )
    assert result[("software.suspicious_name", "")]["result"] == "unknown"
    assert result[("software.threat_intel", "")]["result"] == "unknown"


def test_no_source_record_vulnerability_is_supported():
    result = _by_rule(source_records.evaluate_record(_record(), {}, []))[
        ("software.vulnerability", "")
    ]
    assert result["result"] == "supported"
    assert result["finding"] is None


def test_computer_owned_vulnerability_is_not_duplicated_on_record():
    risks = [
        {
            "canonical_name": "bad app",
            "version": "1",
            "cve": "CVE-2026-1",
            "cvss": 9.8,
            "kev": True,
            "owned_by_computer": True,
        }
    ]
    result = _by_rule(source_records.evaluate_record(_record(), {}, risks))[
        ("software.vulnerability", "")
    ]
    assert result["result"] == "contradicted"
    assert result["owner"] == "computer_software_finding"
    assert result["finding"] is None


def test_disabled_vulnerability_policy_is_unknown_and_does_not_clear():
    result = _by_rule(
        source_records.evaluate_record(_record(), {}, [], software_risk_enabled=False)
    )[("software.vulnerability", "")]
    assert result["result"] == "unknown"
    assert result["finding"] is None
    assert result["missing"] == ["vulnerable_software_enabled"]


def test_pending_candidate_owns_identity_work():
    two = {uuid.uuid4(): {"serial"}, uuid.uuid4(): {"mac"}}
    result = _by_rule(
        source_records.evaluate_record(_record(candidate_pending=True), two)
    )[("identity.association", "")]
    assert result["result"] == "unknown"
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


def test_malformed_mac_is_source_record_work_and_missing_mac_is_unknown():
    malformed = _by_rule(
        source_records.evaluate_record(
            _record(canonical_data={"serial_number": "ABC12345", "macs": ["bad"]}),
            {},
        )
    )[("identifier.validity", "mac")]
    missing = _by_rule(
        source_records.evaluate_record(
            _record(canonical_data={"serial_number": "ABC12345"}), {}
        )
    )[("identifier.validity", "mac")]

    assert malformed["result"] == "contradicted"
    assert malformed["finding"] == {
        "type": "source_record_identifier_invalid",
        "severity": "high",
    }
    assert malformed["evidence"]["invalid_values"] == ["bad"]
    assert missing["result"] == "unknown"
    assert missing["missing"] == ["macs"]


def test_attached_junk_mac_stays_owned_by_legacy_computer_finding():
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                device_id=uuid.uuid4(),
                device_live=True,
                canonical_data={
                    "serial_number": "ABC12345",
                    "macs": ["00:00:00:00:00:00"],
                },
            ),
            {},
        )
    )[("identifier.validity", "mac")]

    assert result["result"] == "contradicted"
    assert result["owner"] == "legacy:placeholder_mac"
    assert result["finding"] is None


@pytest.mark.parametrize(
    ("verdict", "legacy", "expected", "owner", "finding"),
    [
        ("linked", False, "supported", "", None),
        (
            "stale",
            False,
            "contradicted",
            "",
            {"type": "source_record_reference_review", "severity": "medium"},
        ),
        ("stale", True, "contradicted", "legacy:cmdb_asset_stale", None),
        ("divergent", True, "contradicted", "legacy:cmdb_link_incorrect", None),
        ("unlinked", False, "unknown", "", None),
    ],
)
def test_hudu_reference_rule_preserves_existing_owner(
    verdict, legacy, expected, owner, finding
):
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                platform="Hudu",
                entity_type="cmdb.asset",
                record_role="documentation",
                canonical_data={"link_verdict": verdict},
                legacy_stale_reference=legacy and verdict == "stale",
                legacy_divergent_reference=legacy and verdict == "divergent",
            ),
            {},
        )
    )[("record.reference", "hudu_device_reference")]

    assert result["result"] == expected
    assert result["owner"] == owner
    assert result["finding"] == finding


def test_unknown_hudu_reference_does_not_resolve_existing_review():
    record_id = uuid.uuid4()
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                platform="Hudu",
                entity_type="cmdb.asset",
                record_role="documentation",
                canonical_data={"link_verdict": "unlinked"},
            ),
            {},
        )
    )[("record.reference", "hudu_device_reference")]

    class Cursor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("unknown reference evidence must preserve open work")

    source_records.publish_finding(
        Cursor(),
        1,
        {"source_record_reference_review": 12},
        "source_record",
        record_id,
        result,
        datetime(2026, 10, 30, tzinfo=UTC),
        client_id=None,
        context={},
    )


def test_restricted_record_mac_evidence_does_not_expose_values():
    result = _by_rule(
        source_records.evaluate_record(
            _record(
                restricted=True,
                canonical_data={"serial_number": "ABC12345", "macs": ["private-bad"]},
            ),
            {},
        )
    )[("identifier.validity", "mac")]

    assert result["result"] == "contradicted"
    assert result["evidence"] == {"invalid_count": 1}


def test_unknown_identifier_assessment_does_not_clear_existing_finding():
    record_id = uuid.uuid4()
    result = _by_rule(
        source_records.evaluate_record(_record(canonical_data={"hostname": "pc1"}), {})
    )[("identifier.validity", "mac")]

    class Cursor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("unknown identifier evidence must preserve open work")

    finding_id = source_records.publish_finding(
        Cursor(),
        1,
        {"source_record_identifier_invalid": 10},
        "source_record",
        record_id,
        result,
        datetime(2026, 10, 30, tzinfo=UTC),
        client_id=None,
        context={},
    )

    assert result["result"] == "unknown"
    assert finding_id is None


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
