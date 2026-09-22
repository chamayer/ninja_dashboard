"""Regression checks for fail-closed condition subscribers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_notifications_require_current_assessment_for_entity_and_admin():
    query_source = (Path(__file__).parents[2] / "ingest" / "notifications.py").read_text()
    assert "assessment.response ->> 'may_notify'" in query_source
    assert "assessment.assessed_at >= now()" in query_source
    assert "f.snoozed_until <= now()" in query_source
    assert "af.id" in query_source


def test_source_action_recheck_has_finding_and_participant_guards():
    query = (Path(__file__).parents[1] / "source_actions.py").read_text()
    assert "finding.status IN ('open', 'acknowledged')" in query
    assert "condition_participants" in query
    assert "finding.snoozed_until <= now()" in query
    assert "policy->>'freshness_hours'" in query
    assert "finding_type.name = 'cmdb_asset_stale'" in query
    assert "finding.finding_details->>'source_instance_id'" in query
    assert "may_execute')::boolean IS TRUE" in query
    assert "may_clear" not in query


def test_empty_results_require_explicit_complete_coverage_before_clearing():
    evaluator = (Path(__file__).parents[1] / "evaluator.py").read_text()
    cmdb = (Path(__file__).parents[1] / "cmdb_findings.py").read_text()
    patch = (Path(__file__).parents[1] / "patch_findings.py").read_text()
    assert "if not current_subject_ids and not empty_result_verified:" in evaluator
    assert "empty_result_verified: bool = False" in evaluator
    assert "if not keys and not empty_result_verified:" in cmdb
    assert "empty_result_verified: bool = False" in cmdb
    assert "list(emitted_keys) if emitted_keys else [\"\"]" in patch


def test_source_action_worker_preserves_legacy_target_identity():
    source = (Path(__file__).parents[1] / "source_actions.py").read_text()
    assert "request.parent_external_id" in source
    assert "request.external_id" in source
    assert '"company_id", "asset_id"' in source
    assert "request_row[\"company_id\"]" in source
    assert "request_row[\"asset_id\"]" in source


def test_source_action_rechecks_after_queue_selection_before_mutation():
    source = (Path(__file__).parents[1] / "source_actions.py").read_text()
    process = source[source.index("def _process_one"):source.index("def _still_eligible")]
    eligibility = source[source.index("def _still_eligible"):source.index("def _finish")]
    assert "if not _still_eligible(request_row):" in process
    assert process.index("_still_eligible(request_row)") < process.index("archive_asset(")
    for required in (
        "finding.status IN ('open', 'acknowledged')",
        "finding.snoozed_until <= now()",
        "response ->> 'may_execute'",
        "condition_participants",
        "policy_version",
        "policy->>'freshness_hours'",
        "entity_observation_current",
        "canonical_data->>'link_verdict' = 'stale'",
    ):
        assert required in eligibility


def test_source_action_cancels_when_final_recheck_finds_transition(monkeypatch):
    pytest.importorskip("httpx")
    from ingest import source_actions

    source_instance_id = uuid4()
    request_row = {
        "id": 17,
        "finding_id": uuid4(),
        "source_instance_id": source_instance_id,
        "action_key": "archive_hudu_asset",
        "company_id": "company-1",
        "asset_id": "asset-1",
    }
    finished = []
    monkeypatch.setattr(
        source_actions,
        "load_sources",
        lambda: [SimpleNamespace(source_instance_id=source_instance_id, platform="Hudu")],
    )
    monkeypatch.setattr(source_actions, "_still_eligible", lambda row: False)
    monkeypatch.setattr(
        source_actions,
        "_finish",
        lambda request_id, status, **kwargs: finished.append((request_id, status, kwargs)),
    )
    monkeypatch.setattr(
        source_actions,
        "archive_asset",
        lambda *args, **kwargs: pytest.fail("external mutation must not run"),
    )

    status, returned_source = source_actions._process_one(request_row)

    assert status == "cancelled"
    assert returned_source is not None
    assert finished == [(17, "cancelled", {"error": "Target no longer meets the archive rule"})]


def test_assessment_writers_reconcile_removed_participant_scopes():
    ingest_source = (Path(__file__).parents[1] / "conditions.py").read_text()
    operations_source = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "conditions"
        / "live.py"
    ).read_text()
    for source in (ingest_source, operations_source):
        assert "reconcile_condition_participants" in source
        assert "currentness" in source


def test_evaluator_absent_closure_defaults_to_fail_closed():
    source = (Path(__file__).parents[1] / "evaluator.py").read_text()
    signature = source[source.index("def _resolve_findings_absent"):]
    assert "assessment_required: bool = True" in signature
    assert "assessment.response ->> 'may_clear'" in signature


def test_cmdb_absent_closure_never_bypasses_missing_assessments():
    source = (Path(__file__).parents[1] / "cmdb_findings.py").read_text()
    # The call sites are below the helper that performs the closure, so keep
    # them in the contract slice as well.
    section = source[source.index("def _resolve_absent"):]
    assert "if not assessment_required:" in section
    assert "return" in section.split("if not assessment_required:", 1)[1]
    assert section.count("assessment_required=True") >= 4


def test_evaluator_lifecycle_absent_closure_requires_current_clear_assessment():
    source = (Path(__file__).parents[1] / "evaluator.py").read_text()
    signature = source[source.index("def _resolve_lifecycle_findings_absent"):]
    assert signature.count("condition_assessments") >= 2
    assert signature.count("(a.response->>'may_clear')::boolean IS TRUE") >= 2
    assert "p.active" in signature


def test_software_auto_clear_requires_current_assessment_and_participants():
    source = (Path(__file__).parents[1] / "software_findings.py").read_text()
    signature = source[source.index("def _auto_resolve"):]
    assert "may_clear" in signature
    assert "condition_participants" in signature
    assert "participant_role <> 'context'" in signature
    assert "p.active" in signature or "pp.active" in signature


def test_client_resolver_only_closes_after_clear_decision():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    signature = source[source.index("def _resolve_finding"):source.index("def _record_resolver_assessment")]
    assert "assessment.get(\"may_clear\")" in signature
    assert "return" in signature.split("assessment.get(\"may_clear\")", 1)[1]


def test_automatic_clear_does_not_close_operator_managed_episodes():
    evaluator = (Path(__file__).parents[1] / "evaluator.py").read_text()
    resolver = (Path(__file__).parents[1] / "identity" / "resolver.py").read_text()
    lifecycle = evaluator[
        evaluator.index("def _resolve_lifecycle_findings_absent"):
        evaluator.index("_LIFECYCLE_FINDING_ACTIVE_STATUSES")
    ]
    conflict = resolver[
        resolver.index("_IDENTITY_CONFLICT_FINDING_CLOSE"):
        resolver.index("def _project_identity_conflict_findings")
    ]
    assert "status IN ('open', 'acknowledged')" in lifecycle
    assert "'investigating', 'suppressed'" not in lifecycle
    assert "status IN ('open', 'acknowledged')" in conflict
    assert "'investigating')" not in conflict


def test_windows_servicing_uses_measured_identity_evidence():
    source = (Path(__file__).parents[1] / "intel" / "windows_servicing.py").read_text()
    section = source[source.index("def _record_assessment"):source.index("def _iso")]
    evidence = (Path(__file__).parents[1] / "condition_evidence.py").read_text()
    assert "device_identity_signal" in section
    assert "entity_id IS NOT NULL" in evidence
    assert "identity_conflict" in evidence
    assert "Readiness.READY" in evidence


def test_software_device_findings_use_shared_measured_identity_evidence():
    source = (Path(__file__).parents[1] / "software_findings.py").read_text()
    assert "device_identity_signal(cur, tenant_id, participant.reference)" in source


def test_platform_health_assessments_use_admin_row_kind():
    source = (Path(__file__).parents[1] / "platform_findings.py").read_text()
    section = source[source.index("def _record_platform_assessment"):source.index("def _queue_is_measurable")]
    assert '"admin"' in section
    assert '"entity"' not in section
    assert 'Participant("platform_signal"' in section
    assert 'Participant("source_binding"' not in section


def test_platform_health_absent_resolution_targets_admin_findings():
    source = (Path(__file__).parents[1] / "platform_findings.py").read_text()
    section = source[source.index("def _resolve_admin_absent"):source.index("def _eval_source_failures")]
    assert "UPDATE operations.admin_findings" in section
    assert "assessment.row_kind = 'admin'" in section
    assert "may_clear" in section


def test_assessment_policy_digest_is_required_and_bound_to_version():
    migration = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "migrations"
        / "0163_condition_assessment_policy_digest.py"
    ).read_text()
    assert "policy_digest SET NOT NULL" in migration
    assert "FOREIGN KEY (policy_version, policy_digest)" in migration
    assert "a.policy_version, a.policy_digest, a.coverage" in migration
    assert "DROP VIEW operations.v_condition_assessment_current" in migration
    assert "GRANT SELECT ON operations.v_condition_assessment_current" in migration
    assert "DROP CONSTRAINT IF EXISTS fk_condition_assessment_policy_digest" in migration


def test_policy_authority_migration_serializes_activation_and_validates_structure():
    migration = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "migrations"
        / "0162_harden_condition_policy_authority.py"
    ).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in migration
    assert "p_policy->>'schema_version'" in migration
    assert "p_policy->>'version'" in migration
    assert "p_digest !~ '^[0-9a-f]{64}$'" in migration
    assert "WHERE active" in migration


def test_policy_activation_invalidates_old_assessment_authority_atomically():
    migration = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "migrations"
        / "0165_govern_condition_policy_activation.py"
    ).read_text(encoding="utf-8")
    activation = migration[migration.index("CREATE OR REPLACE FUNCTION operations.activate_condition_policy_version"):]
    assert "UPDATE operations.condition_assessments" in activation
    assert "'may_notify', false" in activation
    assert "'may_execute', false" in activation
    assert "'may_clear', false" in activation
    assert "'invalidated_reason', 'policy_activated'" in activation
    assert "policy_version <> p_version" in activation


def test_identity_cleanup_fails_closed_without_assessment_table():
    source = (Path(__file__).parents[1] / "identity" / "resolver.py").read_text()
    section = source[source.index("close_sql = _IDENTITY_CONFLICT_FINDING_CLOSE.replace"):
                     source.index("cur.execute(\n        close_sql", source.index("close_sql ="))]
    assert 'else "   AND FALSE\\n"' in section


def test_assessment_watermark_includes_policy_coverage_participant_and_signals():
    ingest_source = (Path(__file__).parents[1] / "conditions.py").read_text()
    operations_source = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "conditions"
        / "live.py"
    ).read_text()
    for source in (ingest_source, operations_source):
        assert '"policy_digest"' in source
        assert '"coverage"' in source
        assert '"participant"' in source
        assert '"handling"' in source
        assert '"participants"' in source
        assert '"signals"' in source
        assert "signal_watermark" in source


def test_notification_dispatch_rechecks_before_send():
    source = (Path(__file__).parents[1] / "notifications.py").read_text()
    dispatch = source[source.index("def dispatch"):source.index("def _load_rules")]
    assert "_still_notifyable(f, tenant_id)" in dispatch
    helper = source[source.index("def _still_notifyable"):source.index("def _load_rules")]
    assert "snoozed_until" in helper
    assert "condition_participants" in helper
    assert "may_notify" in helper
    assert "may_clear" not in helper
    assert "p.active" in helper


def test_digest_rechecks_selected_findings_before_send():
    source = (Path(__file__).parents[1] / "notifications_digest.py").read_text()
    assert "_still_notifyable" in source
    assert 'f.id AS finding_id' in source
    assert "selection changed before send" in source


def test_admin_notifications_require_non_context_participants():
    source = (Path(__file__).parents[1] / "notifications.py").read_text()
    admin = source[source.index("FROM operations.admin_findings"):source.index("def _load_route")]
    assert "participant.row_kind = 'admin'" in admin
    assert "pa.response ->> 'may_notify'" in admin
    assert "assessment.participant_kind = 'condition'" not in admin


def test_notification_recheck_accepts_participant_assessments_without_aggregate_row():
    source = (Path(__file__).parents[1] / "notifications.py").read_text()
    helper = source[source.index("def _still_notifyable"):source.index("def _load_rules")]
    assert "authority.participant_kind" not in helper
    assert "authority.response->>'may_notify'" in helper
    assert "NOT EXISTS" in helper


def test_critical_priority_only_blocks_lower_findings_with_complete_authority():
    from ingest.condition_priority import critical_priority_clause

    clause = critical_priority_clause("finding")
    assert "finding.severity NOT IN ('medium', 'low', 'info')" in clause
    assert "expected_scope" in clause
    assert "participant_kind = 'condition'" in clause
    assert clause.count("(") == clause.count(")")


def test_notification_union_closes_entity_predicate_before_admin_branch():
    source = (Path(__file__).parents[1] / "notifications.py").read_text()
    entity = source[source.index("def _load_pending_findings"):source.index("def _load_route")]
    union = entity.index("UNION ALL")
    assert ")\n          {critical_priority_clause('f')}" in entity[:union]


def test_identity_readiness_covers_group_members_and_reviewed_distinct_decisions():
    source = (Path(__file__).parents[1] / "condition_evidence.py").read_text()
    assert "candidate_device_ids" in source
    assert "condition_reviewed_distinct" in source
    assert "membership_fingerprint" in source
    assert "evidence_fingerprint" in source
    assert "pg_catalog.sha256(convert_to" in source
    assert "digest(" not in source


def test_snapshot_and_software_exposure_require_fresh_authority():
    evidence = (Path(__file__).parents[1] / "condition_evidence.py").read_text()
    assert "max_age_hours: int = 24" in evidence
    migration = (
        Path(__file__).parents[2] / "sql" / "migrations" / "109_condition_gated_software_exposure.sql"
    ).read_text()
    assert "assessment.participant_kind = 'device'" in migration
    assert "assessment.response->>'may_execute'" in migration
    assert "freshness_hours" in migration
    assert "GRANT SELECT ON operations.condition_assessments" in migration
    assert "TO operations_view_owner" in migration


def test_patch_assessments_measure_identity_offline_and_coverage():
    source = (Path(__file__).parents[1] / "patch_findings.py").read_text()
    section = source[source.index("def _record_assessment"):source.index("def _auto_resolve")]
    assert "device_identity_signal" in section
    assert "offline_readiness" in section
    assert "_patch_evaluation_coverage" in section
    assert "EvaluationCoverage(measured, measured, measured, measured)" in source
    assert "reported_online IS TRUE" in source
    assert "no_longer_actionable" in source
    assert source.count("external_id::int") == source.count("external_id ~ '^[0-9]+$'")


def test_software_assessments_cover_each_device_and_measure_contact():
    source = (Path(__file__).parents[1] / "software_findings.py").read_text()
    section = source[source.index("def _emit_scoped"):source.index("def _auto_resolve")]
    assert "already_emitted" in section
    assert "device_agent_presence_current" in section
    assert "offline_readiness" in section
    assert "offline:contact_unavailable" not in section
    assert "all_devices" in section
    assert "participants.extend" in section


def test_snapshot_chooses_latest_run_before_validating_status():
    source = (Path(__file__).parents[1] / "condition_evidence.py").read_text()
    section = source[source.index("def complete_snapshot_available"):source.index("def device_identity_signals")]
    assert "ORDER BY GREATEST" in section
    assert "AND status = 'complete'" not in section


def test_patch_recovery_requires_current_source_evidence_and_allows_empty_runs():
    source = (Path(__file__).parents[1] / "patch_findings.py").read_text()
    coverage = source[source.index("def _patch_evaluation_coverage"):source.index("def _auto_resolve")]
    recovery = source[source.index("def _auto_resolve"):]
    assert "device_patch_signal signal" in coverage
    assert "reported_online IS TRUE" in coverage
    assert "if not emitted_keys" not in recovery
    assert "f.subject_type = 'client'" in recovery
    assert "patch_approval_backlog" in recovery
    assert "NOT EXISTS (\n                  SELECT 1\n                    FROM operations.v_device client_device" in recovery
    assert "effective_patching_scope = 'Included'" in recovery
    assert "lifecycle_status <> 'retired'" in recovery
    assert "latest_patch_run" in recovery
    assert "last_observed_at = run.snapshot_at" in recovery
    assert "condition_assessments a" in recovery
    migration = (Path(__file__).parents[2] / "sql" / "migrations" / "111_patch_run_snapshot_association.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS snapshot_at" in migration


def test_ninja_materialized_view_refreshes_set_tenant_context():
    for name in ("devices.py", "device_health.py", "custom_fields.py"):
        source = (Path(__file__).parents[1] / "core" / name).read_text()
        assert "SET LOCAL operations.tenant_id" in source


def test_review_workflow_uses_integer_django_user_ids_and_has_endpoint():
    migration = (
        Path(__file__).parents[2]
        / "operations"
        / "apps"
        / "core"
        / "migrations"
        / "0169_align_condition_reviewer_ids.py"
    ).read_text()
    assert "ALTER COLUMN reviewer_id TYPE BIGINT" in migration
    assert "p_reviewer BIGINT" in migration
    views = (Path(__file__).parents[2] / "operations" / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    urls = (Path(__file__).parents[2] / "operations" / "config" / "urls.py").read_text(encoding="utf-8")
    assert "record_identity_reviewed_distinct" in views
    assert "finding_reviewed_distinct" in urls
