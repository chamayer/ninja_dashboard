from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.core.conditions.contracts import (
    Condition,
    EvaluationCoverage,
    Participant,
    Readiness,
    Signal,
)
from apps.core.conditions.engine import assess
from apps.core.conditions.policy import load_profile, parse_profile
from apps.core.conditions.reader import Snapshot
from apps.core.conditions.report import build_report

NOW = datetime(2026, 9, 14, tzinfo=UTC)
DEVICE = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"


@pytest.fixture(scope="module")
def effective_condition_states():
    """Shared response fixtures for subscriber acceptance tests."""
    return {
        "eligible": {
            "disposition": "eligible",
            "available": True,
            "may_notify": True,
            "may_execute": True,
            "may_clear": True,
        },
        "blocked": {
            "disposition": "blocked",
            "available": True,
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
        "pending": {
            "disposition": "unknown",
            "available": True,
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
        "stale": {
            "disposition": "unknown",
            "available": True,
            "coverage_recovery_required": True,
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
        "suppressed": {
            "disposition": "suppressed",
            "available": True,
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
        "snoozed": {
            "disposition": "suppressed",
            "available": True,
            "reasons": ["existing_operator_suppression"],
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
        "missing_policy": {
            "disposition": "unknown",
            "available": False,
            "may_notify": False,
            "may_execute": False,
            "may_clear": False,
        },
    }


def test_effective_condition_state_fixtures_fail_closed(effective_condition_states):
    for name, response in effective_condition_states.items():
        if name == "eligible":
            assert response["may_notify"] and response["may_execute"]
            continue
        assert not response["may_notify"]
        assert not response["may_execute"]
        assert not response["may_clear"]


@pytest.mark.parametrize(
    "subscriber",
    (
        "notifications",
        "digest",
        "source_action_queue",
        "source_action_worker",
        "retirement_and_merge",
        "software_exposure",
        "issues_and_admin_health",
        "device_client_software_patch_pages",
        "navigation_dashboard_workspace",
        "health_history",
        "api_csv_search_report_metabase",
        "legacy_external_sql",
    ),
)
def test_subscriber_state_matrix_is_fail_closed_for_noneligible_states(
    effective_condition_states, subscriber
):
    """Every subscriber shares the same retained-versus-authorized state contract."""
    assert subscriber
    for state, response in effective_condition_states.items():
        if state == "eligible":
            assert response["may_notify"] and response["may_execute"]
        else:
            assert not response["may_notify"]
            assert not response["may_execute"]
            assert not response["may_clear"]


def participant(reference=DEVICE, kind="device", role="affected", tenant_id=1):
    return Participant(kind, reference, role, tenant_id)


def condition(name="patching_stalled", members=None, **changes):
    value = Condition(
        1,
        "entity",
        "finding-1",
        name,
        "stable-key",
        "open",
        tuple(members) if members is not None else (participant(),),
    )
    return replace(value, **changes)


def signal(name, readiness, member=None):
    return Signal(name, member or participant(), readiness, f"{name}:{readiness}", ("blocker",))


def test_profile_covers_53_definitions_and_all_subscribers():
    profile = load_profile()
    assert len(profile.definitions) == 53
    assert len(profile.consumers) == 10
    assert profile.definitions["cmdb_asset_stale"]["label"] == "Hudu archive candidate"
    assert (
        profile.definitions["patch_approval_backlog"]["label"]
        == "Approved patches awaiting installation"
    )
    assert profile.definitions["identity_conflict"]["rules"] == []
    assert profile.definitions["device_long_offline"]["lifecycle"] == "historical"
    assert profile.definitions["identity_resolution_pending"]["lifecycle"] == "unverified"


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "cycle", "unknown_rule", "threshold", "effect", "bad_shape", "bad_alias"],
)
def test_invalid_profile_rejected(mutation):
    path = Path(__file__).parents[4] / "shared" / "conditions" / "profile.json"
    data = json.loads(path.read_text())
    if mutation == "duplicate":
        data["definitions"].append(data["definitions"][0])
    elif mutation == "cycle":
        data["rules"]["identity"]["requires"] = ["offline"]
        data["rules"]["offline"]["requires"] = ["identity"]
    elif mutation == "unknown_rule":
        data["definitions"][0]["rules"] = ["invented"]
    elif mutation == "threshold":
        data["offline_days"] = 0
    elif mutation == "effect":
        data["rules"]["identity"]["effect"] = "execute_code"
    elif mutation == "bad_shape":
        data["rules"]["identity"]["requires"] = [{"not": "a rule"}]
    else:
        data["issue_type_aliases"][0]["types"].append("not_registered")
    with pytest.raises(ValueError):
        parse_profile(data)


@pytest.mark.parametrize("status", ["acknowledged", "investigating", "suppressed", "resolved"])
def test_stable_identity_survives_handling_and_membership(status):
    original = condition()
    changed = replace(
        original,
        status=status,
        row_id="another-episode",
        participants=(participant(), participant(OTHER)),
    )
    assert changed.identity == original.identity
    assert replace(original, row_kind="admin").identity != original.identity
    assert replace(original, condition_key="").identity != original.identity
    assert replace(original, tenant_id=2, participants=()).identity != original.identity


def test_cross_tenant_and_non_member_inputs_rejected():
    with pytest.raises(ValueError, match="Cross-tenant"):
        condition(members=(participant(tenant_id=2),))
    with pytest.raises(ValueError, match="not a member"):
        assess(condition(), load_profile(), (), NOW, participant(OTHER))


def test_invalid_signal_and_handling_cannot_default_to_eligible():
    with pytest.raises(ValueError, match="signal"):
        Signal("identity", participant(), "invented", "reason")
    with pytest.raises(ValueError, match="handling"):
        condition(status="invented")
    with pytest.raises(ValueError, match="timezone"):
        condition(snoozed_until=datetime(2026, 9, 14))


@pytest.mark.parametrize("field", ["succeeded", "complete", "fresh", "scope_matches"])
def test_clearing_requires_all_coverage_dimensions(field):
    coverage = EvaluationCoverage(True, True, True, True)
    assert coverage.permits_clearing
    assert not replace(coverage, **{field: False}).permits_clearing


def test_identity_blocks_all_responses_but_does_not_clear_condition():
    row = condition()
    result = assess(
        row,
        load_profile(),
        (signal("identity", Readiness.BLOCKED), signal("offline", Readiness.READY)),
        NOW,
        participant(),
    )
    assert result.disposition == "blocked"
    assert not result.may_evaluate and not result.may_notify and not result.may_execute
    assert row.status == "open"
    assert result.blockers == ("blocker",)


def test_identity_work_does_not_block_itself():
    result = assess(
        condition("identity_conflict"),
        load_profile(),
        (signal("identity", Readiness.BLOCKED),),
        NOW,
        participant(),
    )
    assert result.disposition == "eligible"


def test_offline_suppresses_attention_not_observation():
    result = assess(
        condition(),
        load_profile(),
        (signal("identity", Readiness.READY), signal("offline", Readiness.BLOCKED)),
        NOW,
        participant(),
    )
    assert result.disposition == "suppressed"
    assert result.may_evaluate
    assert not result.may_notify and not result.may_execute


def test_recovery_with_missing_evidence_does_not_release_responses():
    result = assess(
        condition(), load_profile(), (signal("identity", Readiness.READY),), NOW, participant()
    )
    assert result.disposition == "unknown"
    assert not result.may_execute


def test_one_participant_does_not_block_another_or_global_fact():
    software = participant("version", "software_version")
    first = participant(role="candidate_software_exposure")
    second = participant(OTHER, role="candidate_software_exposure")
    row = condition("vulnerable_software", (software, first, second))
    signals = (
        signal("identity", Readiness.BLOCKED, first),
        signal("identity", Readiness.READY, second),
    )
    assert assess(row, load_profile(), signals, NOW, first).disposition == "blocked"
    assert assess(row, load_profile(), signals, NOW, second).disposition == "eligible"
    assert assess(row, load_profile(), signals, NOW, software).disposition == "eligible"


def test_context_participant_is_not_an_action_scope_and_all_members_must_pass():
    affected = participant(role="candidate_software_exposure")
    other = participant(OTHER, role="candidate_software_exposure")
    context = participant("00000000-0000-0000-0000-000000000003", "client", "context")
    row = condition("vulnerable_software", (affected, other, context))
    signals = (
        signal("identity", Readiness.READY, affected),
        signal("identity", Readiness.BLOCKED, other),
    )
    assert assess(row, load_profile(), signals, NOW, affected).may_execute
    assert not assess(row, load_profile(), signals, NOW, other).may_execute
    assert context.role == "context"


def test_mixed_global_software_and_device_scopes_require_all_action_members():
    software = participant("00000000-0000-0000-0000-000000000010", "software_version")
    blocked_device = participant("00000000-0000-0000-0000-000000000011", role="candidate_software_exposure")
    eligible_device = participant("00000000-0000-0000-0000-000000000012", role="candidate_software_exposure")
    client_context = participant(
        "00000000-0000-0000-0000-000000000013", "client", "context"
    )
    row = condition(
        "vulnerable_software",
        (software, blocked_device, eligible_device, client_context),
    )
    signals = (
        signal("identity", Readiness.BLOCKED, blocked_device),
        signal("identity", Readiness.READY, eligible_device),
    )

    assert assess(row, load_profile(), signals, NOW, software).may_execute
    assert not assess(row, load_profile(), signals, NOW, blocked_device).may_execute
    assert assess(row, load_profile(), signals, NOW, eligible_device).may_execute
    # Context identifies the client but is not an action scope and must not
    # turn an otherwise eligible device set into a pending action.
    assert assess(row, load_profile(), signals, NOW, client_context).may_execute


def test_client_aggregate_without_members_is_unknown():
    client = participant("client", "client")
    row = condition("patch_approval_backlog", (client,))
    assert assess(row, load_profile(), (), NOW, client).disposition == "unknown"


def test_snooze_is_preserved_and_expiry_does_not_bypass_prerequisites():
    row = condition(snoozed_until=NOW + timedelta(days=1))
    result = assess(row, load_profile(), (), NOW, participant())
    assert "existing_operator_suppression" in result.reasons
    assert result.disposition == "unknown"
    row = replace(row, snoozed_until=NOW - timedelta(days=1))
    assert assess(row, load_profile(), (), NOW, participant()).disposition == "unknown"


def finding(name, identifier, subject=DEVICE, **changes):
    return {
        "row_kind": "entity",
        "row_id": identifier,
        "type_name": name,
        "condition_key": identifier,
        "status": "open",
        "subject_type": "device",
        "subject_id": subject,
        "client_id": None,
        "snoozed_until": None,
        "candidate_ids": None,
        "source_instance_id": None,
        "snapshot_scope": None,
        **changes,
    }


def snapshot(findings, **changes):
    return Snapshot(
        1,
        NOW,
        [{"name": name} for name in load_profile().definitions],
        findings,
        [
            {"device_id": DEVICE, "client_id": "client", "lifecycle_status": "active"},
            {"device_id": OTHER, "client_id": "client", "lifecycle_status": "active"},
        ],
        changes.get("presence", []),
        changes.get("associations", []),
        changes.get("collections", []),
        changes.get("consumers", []),
    )


def test_report_identity_membership_no_double_count_and_no_private_output():
    rows = [
        finding("identity_conflict", "private-id", candidate_ids=[DEVICE, OTHER]),
        finding("patching_stalled", "patch"),
        finding("vulnerable_software", "vuln", "version", subject_type="software_version"),
    ]
    sample = snapshot(
        rows,
        associations=[
            {
                "row_id": "vuln",
                "device_id": DEVICE,
                "association_kind": "candidate_software_exposure",
            },
            {
                "row_id": "vuln",
                "device_id": OTHER,
                "association_kind": "candidate_software_exposure",
            },
        ],
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["identity_group_devices"] == 2
    assert result["comparison"]["active_rows_with_identity_blocked_participants"] == 2
    assert result["comparison"]["identity_blocked_candidate_exposure_pairs"] == 2
    assert result["comparison"]["rows_with_mixed_participant_dispositions"] == 1
    assert DEVICE not in json.dumps(result)
    assert "private-id" not in json.dumps(result)


def test_invalid_group_members_do_not_cross_tenant_or_silently_become_ready():
    sample = snapshot(
        [
            finding("identity_conflict", "group", candidate_ids=[DEVICE, "invalid"]),
            finding("patching_stalled", "patch"),
        ]
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["identity_group_devices"] == 0
    assert result["comparison"]["invalid_or_unavailable_identity_members"] > 0
    assert result["by_type"]["patching_stalled"]["dispositions"] == {"unknown": 1}


def test_raw_cursor_json_string_is_decoded_for_identity_members():
    sample = snapshot(
        [
            finding("identity_conflict", "group", candidate_ids=json.dumps([DEVICE, OTHER])),
            finding("patching_stalled", "patch"),
        ]
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["identity_group_devices"] == 2
    assert result["comparison"]["active_rows_with_identity_blocked_participants"] == 1


def test_collection_missing_scope_is_unknown_even_when_other_snapshots_succeed():
    sample = snapshot([finding("cmdb_asset_stale", "archive", subject_type="source_binding")])
    result = build_report(sample, load_profile())
    assert result["by_type"]["cmdb_asset_stale"]["reasons"]["collection:scope_unmapped"] == 1


def test_recent_failure_blocks_collection_even_with_complete_flag():
    record = {
        "source_instance_id": DEVICE,
        "snapshot_scope": "devices",
        "status": "failed",
        "is_complete_snapshot": True,
        "failed_rows": 1,
        "written_rows": 1,
        "expected_rows": 2,
        "completed_at": NOW,
        "run_started_at": NOW,
    }
    sample = snapshot(
        [
            finding(
                "cmdb_asset_stale",
                "archive",
                subject_type="source_binding",
                source_instance_id=DEVICE,
                snapshot_scope="devices",
            )
        ],
        collections=[record],
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["active_rows_with_collection_block_reason"] == 1


def test_old_contact_with_online_claim_is_unknown_not_suppressed():
    sample = snapshot(
        [finding("patching_stalled", "patch")],
        presence=[
            {
                "device_id": DEVICE,
                "last_contact": NOW - timedelta(days=365),
                "any_reported_online": True,
            }
        ],
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["active_rows_with_offline_suppression_reason"] == 0
    assert (
        result["by_type"]["patching_stalled"]["reasons"]["offline:conflicting_online_evidence"] == 1
    )


def test_retained_suppressed_rows_are_not_counted_as_new_active_impact():
    sample = snapshot(
        [
            finding("identity_conflict", "group", candidate_ids=[DEVICE, OTHER]),
            finding("patching_stalled", "patch", status="suppressed"),
        ]
    )
    result = build_report(sample, load_profile())
    assert result["comparison"]["active_rows_with_identity_blocked_participants"] == 0
    assert result["by_type"]["patching_stalled"]["reasons"]["existing_operator_suppression"] == 1


def test_issue_taxonomy_covers_every_condition_once():
    profile = load_profile()
    memberships = [
        condition
        for category in profile.issue_taxonomy
        for type_item in category["types"]
        for condition in type_item["conditions"]
    ]
    assert len(memberships) == 53
    assert len(set(memberships)) == 53
    assert set(memberships) == set(profile.definitions)
    assert [category["label"] for category in profile.issue_taxonomy] == [
        "Computers",
        "Matching & duplicates",
        "Hudu",
        "Software & security",
        "Patching & Windows",
        "Data collection",
    ]


def test_issue_taxonomy_rejects_cross_type_membership():
    data = json.loads(Path(__file__).parents[4].joinpath("shared/conditions/profile.json").read_text())
    data["issue_taxonomy"][0]["types"][1]["conditions"].append("missing_required_platform")
    with pytest.raises(ValueError, match="multiple taxonomy types"):
        parse_profile(data)
