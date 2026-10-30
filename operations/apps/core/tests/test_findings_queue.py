from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.test import RequestFactory

from apps.core import views
from apps.core.conditions.operator import operator_state
from apps.core.finding_actions import (
    ARCHIVE_HUDU_ASSETS,
    BULK_RETIRE_COMPUTERS,
    COMPUTER_CLIENT_SOURCE_WRONG,
    CONFIRM_COMPUTERS_IN_USE,
    CONFIRM_COMPUTERS_SEPARATE,
    KEEP_COMPUTER_CLIENT,
    MERGE_COMPUTERS,
    MOVE_COMPUTER_CLIENT,
    SPLIT_COMPUTER_RECORDS,
    available_finding_actions,
)
from apps.core.templatetags.human_labels import finding_drilldown_query, humanize_label


def test_operator_issue_type_groups_sort_by_operator_label():
    groups = {
        "zeta": {"value": "zeta", "label": "Zeta type", "types": {"zeta_issue"}},
        "alpha": {"value": "alpha", "label": "Alpha type", "types": {"alpha_issue"}},
    }

    assert [
        group["value"]
        for group in views._operator_issue_type_groups(
            [
                SimpleNamespace(name="zeta_issue"),
                SimpleNamespace(name="alpha_issue"),
            ],
            "",
            [{"key": "inventory", "types": {"zeta_issue", "alpha_issue"}}],
            groups,
        )
    ] == ["alpha", "zeta"]


class _Cursor:
    def __init__(self):
        self.statement = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params):
        self.statement = statement
        self.params = params

    def fetchall(self):
        return [
            (
                "device-1",
                "host-1",
                "Client A",
                "Windows 11 Pro",
                "23H2",
                "22631",
                ["windows_servicing_eol"],
            )
        ]


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Compiler:
    def as_sql(self):
        return "SELECT id FROM filtered_findings WHERE status = %s", ("open",)


class _Query:
    def get_compiler(self, *, connection):
        return _Compiler()


class _Findings:
    query = _Query()

    def order_by(self):
        return self

    def values(self, *_fields):
        return self


def test_affected_device_rows_uses_one_filtered_finding_set(monkeypatch):
    cursor = _Cursor()
    monkeypatch.setattr(views, "connection", _Connection(cursor))

    rows = views._affected_device_rows(_Findings())

    assert "WITH matching AS (SELECT id FROM filtered_findings" in cursor.statement
    assert "operations.v_device_software_exposure" in cursor.statement
    assert cursor.params == ("open",)
    assert rows == [
        {
            "device_id": "device-1",
            "hostname": "host-1",
            "client": "Client A",
            "os_name": "Windows 11 Pro",
            "os_release_id": "23H2",
            "os_build_number": "22631",
            "finding_types": ["windows_servicing_eol"],
        }
    ]


def test_operator_projection_uses_operator_vocabulary_and_short_reasons():
    now = datetime(2026, 9, 18, tzinfo=UTC)
    assert operator_state(
        status="open",
        snoozed_until=None,
        assessment={"disposition": "complete", "may_execute": True},
        now=now,
    ) == {"status": "active", "attention": "needs_action", "reason": "Ready for action"}
    assert operator_state(
        status="open",
        snoozed_until=None,
        assessment={"disposition": "blocked", "blockers": ["offline:extended_absence"]},
        now=now,
    ) == {"status": "active", "attention": "blocked", "reason": "Computer offline"}
    assert operator_state(
        status="open",
        snoozed_until=now + timedelta(hours=1),
        assessment=None,
        now=now,
    ) == {"status": "paused", "attention": "paused", "reason": "Paused by operator"}
    assert (
        operator_state(
            status="acknowledged",
            snoozed_until=None,
            assessment=None,
            now=now,
        )["status"]
        == "active"
    )


def test_patching_scope_labels_explain_the_three_operator_choices():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/patching_queue.html").read_text(encoding="utf-8")

    assert '"label": "In scope — patching expected"' in source
    assert '"label": "Excluded — do not patch"' in source
    assert '"label": "Not managed — no patch service"' in source
    assert "means patching is expected" in template
    assert "means it is intentionally not patched" in template
    assert "means no patching service is assigned" in template


def test_client_patching_compliance_breakdowns_use_the_shared_definition():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/patching_queue.html").read_text(encoding="utf-8")

    assert "COMPLIANCE_MISSING_STATUSES" in source
    assert '"fully-patched"' in source
    assert "Fully patched devices" in template
    assert "By device type" in template
    assert "By operating system" in template


def test_patching_workflows_use_human_labels_and_actions(monkeypatch):
    import importlib

    from apps.core import finding_registry

    seed = importlib.import_module("apps.core.migrations.0295_finding_types_registry").ROWS
    monkeypatch.setattr(
        finding_registry, "_load_names", lambda: {row[0]: row[1] for row in seed}
    )
    assert humanize_label("device_never_patched") == "No patch installed yet"
    assert humanize_label("patching_stalled") == "No recent patch activity"
    assert humanize_label("reboot_pending") == "Restart required"
    assert humanize_label("patch_failing_repeatedly") == "Update repeatedly failing"
    assert humanize_label("patch_approval_backlog") == "Approved updates not installed"
    assert (
        views._PATCHING_WORKFLOW["patch_approval_backlog"]["note"] == "Review the client deployment"
    )


def test_patching_inactive_label_shows_observed_or_threshold_age():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert 'return f"Patching inactive ({age_days}d)"' in source
    assert 'return f"Patching inactive ({patch_activity_threshold}d+)"' in source


class _FindingActionUser:
    is_authenticated = True

    def __init__(self, *, may_manage_lifecycle: bool, may_manage_sources: bool = False) -> None:
        self.is_superuser = False
        self._may_manage_lifecycle = may_manage_lifecycle
        self._may_manage_sources = may_manage_sources

    def has_perm(self, permission: str) -> bool:
        return (permission == "operations.manage_lifecycle" and self._may_manage_lifecycle) or (
            permission == "operations.manage_sources" and self._may_manage_sources
        )


def _permissioned_actions(user):
    # Login-only actions (software decisions) carry no permission; this suite
    # asserts the permission-gated ones.
    return tuple(a for a in available_finding_actions(user) if a.permission)


def test_registered_retirement_action_requires_lifecycle_permission():
    assert _permissioned_actions(_FindingActionUser(may_manage_lifecycle=False)) == ()
    assert _permissioned_actions(_FindingActionUser(may_manage_lifecycle=True)) == (
        BULK_RETIRE_COMPUTERS,
        MERGE_COMPUTERS,
        CONFIRM_COMPUTERS_SEPARATE,
        SPLIT_COMPUTER_RECORDS,
        CONFIRM_COMPUTERS_IN_USE,
        MOVE_COMPUTER_CLIENT,
        KEEP_COMPUTER_CLIENT,
        COMPUTER_CLIENT_SOURCE_WRONG,
    )


def test_manual_retirement_is_visible_without_a_lifecycle_finding_gate():
    template = Path("templates/device_detail.html").read_text(encoding="utf-8")

    assert "Manually retire this Computer" in template
    assert "can_manage_lifecycle and device.lifecycle_status != 'retired'" in template
    assert "Why retire this Computer?" in template


def test_device_source_records_are_unique_and_review_copy_is_truthful():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/device_detail.html").read_text(encoding="utf-8")

    assert "FROM operations.v_device_observation_current evidence" in source
    assert "LEFT JOIN LATERAL (\n              SELECT presence.reported_online" in source
    assert "LIMIT 1\n          ) presence ON TRUE" in source
    assert "evidence.device_id = ANY(%s::uuid[])" in source
    assert "_device_source_records(cur, [device.id]).get(str(device.id), [])" in source
    assert "[str(device.id), 1, str(device.id)]," not in source
    assert "this Computer is outside normal inventory" in template
    assert "no current source record reports this Computer" not in template
    assert "no source currently reports this Computer" not in template


def test_hudu_archive_action_requires_source_management_permission():
    assert _permissioned_actions(
        _FindingActionUser(may_manage_lifecycle=False, may_manage_sources=True)
    ) == (ARCHIVE_HUDU_ASSETS,)


def test_bulk_retirement_fails_closed_without_lifecycle_permission():
    request = RequestFactory().post(
        "/findings/bulk/",
        {"ids": "7e0ae011-9b4e-4a8b-9a74-7c13f7b61123", "action": "retire_computers"},
    )
    request.user = _FindingActionUser(may_manage_lifecycle=False)

    with pytest.raises(PermissionDenied):
        views.findings_bulk_action(request)


def test_registered_evidence_group_drilldown_opens_the_full_group():
    finding = SimpleNamespace(
        finding_type=SimpleNamespace(name="cross_client_serial", drilldown_evidence_key="serial"),
        finding_details={"serial": "AB 123"},
    )

    assert parse_qs(finding_drilldown_query(finding, "device-1")) == {
        "type": ["cross_client_serial"],
        "status": ["all"],
        "group_key": ["serial"],
        "group_value": ["AB 123"],
    }


def test_unregistered_evidence_group_preserves_device_drilldown():
    finding = SimpleNamespace(
        finding_type=SimpleNamespace(name="device_offline", drilldown_evidence_key=""),
        finding_details={},
    )

    assert parse_qs(finding_drilldown_query(finding, "device-1")) == {
        "type": ["device_offline"],
        "status": ["all"],
        "subject_id": ["device-1"],
    }


def test_findings_queue_has_one_category_scheme_and_no_legacy_url_shims():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "requested_category_filter" not in source
    assert "finding_type__category__name" not in source
    assert "finding_categories" not in source


def test_targeted_refresh_uses_the_same_ingest_and_evaluator_paths_as_issues():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    jobs_template = Path("templates/admin_jobs.html").read_text(encoding="utf-8")
    refresh_template = Path("templates/targeted_refresh.html").read_text(encoding="utf-8")
    urls = Path("config/urls.py").read_text(encoding="utf-8")

    assert "def _queue_refresh_for_finding" in source
    assert "def _queue_source_refresh" in source
    assert "def _queue_platform_reevaluation" in source
    assert '"run/platform-evaluate"' in source
    assert "def targeted_refresh" in source
    assert 'row["refresh_available"] = row["operator_attention"] == ATTENTION_PENDING' in source
    assert "Source health" in source
    assert "url 'targeted_refresh'" in jobs_template
    assert "Computer data" in refresh_template
    assert "Source data" in refresh_template
    assert "Reevaluate" in refresh_template
    assert "targeted_refresh" in urls


def test_database_evidence_projection_parenthesizes_json_text_before_concatenation():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    queue = source[
        source.index("def findings_queue") : source.index(
            "def _policy_candidate_state_action_blocked"
        )
    ]
    assert "|| finding_details->>" not in queue


def test_admin_health_is_admin_only():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert (
        "@require_admin"
        in source[
            source.rfind(
                "@login_required", 0, source.index("def findings_admin_health")
            ) : source.index("def findings_admin_health")
        ]
    )
    assert (
        "condition_participants"
        in source[
            source.index("def _condition_coverage_summary") : source.index(
                "def admin_finding_acknowledge"
            )
        ]
    )


def test_findings_queue_does_not_substitute_packaged_taxonomy():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    taxonomy_section = source[
        source.index("def _issue_taxonomy") : source.index("def _condition_assessment_display")
    ]
    assert "load_profile" not in taxonomy_section
    assert "issue_taxonomy" in taxonomy_section


def test_human_label_filter_formats_scoped_condition_reasons():
    source = Path("apps/core/templatetags/human_labels.py").read_text(encoding="utf-8")
    assert 'key.split(":", 1)' in source
    assert "suffix.replace('_', ' ')" in source


def test_condition_response_reads_are_batched():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "for offset in range(0, len(candidate_ids), 1000)" in source
    assert (
        "candidate_ids = [finding_id for finding_id in ids if finding_id in assessed_ids]" in source
    )
    assert "batch = candidate_ids[offset : offset + 1000]" in source
    assert "finding_id for finding_id in ids if finding_id not in assessed_ids" in source
    assert "[batch, batch]" in source


def test_row_states_come_from_the_stored_state_for_the_rows_on_screen():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[
        source.index("def _condition_operator_states") : source.index(
            "def _operator_issue_type_groups"
        )
    ]
    assert "_state_rows().filter(finding_id__in=ids)" in section
    assert "_critical_issue_badges(ids)" in section
    assert "operator_states = _condition_operator_states([f.id for f in findings])" in source
    assert "_condition_response_ids" not in section


def test_findings_queue_template_compiles():
    get_template("findings_queue.html")


def test_device_surface_exposes_governed_response_state():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/device_detail.html").read_text(encoding="utf-8")
    assert "_condition_response_ids(finding.id for finding in active_findings)" in source
    assert "condition_response" in template
    assert "condition_assessment" in source
    assert "policy_digest" in source
    assert "condition_policy_available" in source
    assert "Condition policy unavailable" in template


def test_admin_health_exposes_unavailable_policy_state():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")
    assert '"condition_policy_available": condition_policy_available' in source
    assert "Condition policy is unavailable" in template
    assert '"jobs_health": jobs_health' in source
    assert "Open Job configuration" in template


def test_admin_coverage_tracks_condition_keys_and_links_to_issues():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    template = Path("templates/findings_admin_health.html").read_text(encoding="utf-8")
    assert "f.condition_key AS name" in source
    assert "condition_coverage = _condition_coverage_summary(condition_profile)" in source
    assert "findings_queue" in template
    assert "row.category_key" in template
    assert "row.type_key" in template
    assert "row.name|urlencode" in template


def test_source_action_enqueue_requires_current_actionable_response():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "_condition_operator_states([finding.id])" in source


def test_source_action_actionability_excludes_operator_managed_findings():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    section = source[
        source.index("def _condition_response_ids") : source.index(
            "def _operator_issue_type_groups"
        )
    ]
    assert "f.status IN ('open', 'acknowledged', 'investigating')" in section
    assert "f.snoozed_until IS NULL OR f.snoozed_until <= now()" in section
    assert "may_execute" in section
    assert "may_clear" not in section


def test_operator_resolution_and_retirement_preserve_explicit_reasons():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert '"reason": "operator_resolved"' in source
    assert '"reason": "retired"' in source
    assert (
        "finding_details"
        in source[source.index("def finding_resolve") : source.index("def finding_snooze")]
    )


def _merge_function_sql() -> str:
    # The merge moved from views._merge_devices into one SQL function used by
    # operator and automatic merges (migration 0308); its behavior is covered
    # end to end by test_migration_0308_postgres.py.
    source = Path("apps/core/migrations/0308_computer_merge_and_split.py").read_text(
        encoding="utf-8"
    )
    return source[
        source.index("CREATE FUNCTION operations.merge_computers") : source.index(
            "CREATE FUNCTION operations.split_computer_merge"
        )
    ]


def test_device_merge_preserves_finding_merge_provenance():
    views = Path("apps/core/views.py").read_text(encoding="utf-8")
    assert "operations.merge_computers" in views
    section = _merge_function_sql()
    assert "'merge'" in section
    assert "from_device_id" in section
    assert "into_device_id" in section


def test_device_merge_reconciles_condition_scopes_before_downstream_use():
    section = _merge_function_sql()
    assert "condition_participants" in section
    assert "condition_assessments" in section
    assert "ON CONFLICT DO NOTHING" in section
    assert "source_action_requests" not in section
    assert "UPDATE operations.findings SET id" not in section


def test_client_attachment_resolution_requires_current_clear_assessment():
    source = (Path(__file__).parents[1] / "views.py").read_text(encoding="utf-8")
    section = source[
        source.index("def _attach_group_to_client") : source.index(
            "@login_required", source.index("def _resolve_finding_for_group")
        )
    ]
    assert section.count("condition_assessments") >= 2
    assert section.count("may_clear") >= 2
    assert "policy.active" in section
