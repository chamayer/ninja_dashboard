from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

from apps.core import views
from apps.core.templatetags.human_labels import finding_drilldown_query


def test_finding_type_groups_preserve_category_order_and_other_bucket():
    categories = [
        SimpleNamespace(id=2, name="software"),
        SimpleNamespace(id=1, name="lifecycle"),
    ]
    finding_types = [
        SimpleNamespace(category_id=1, name="windows_servicing_eol"),
        SimpleNamespace(category_id=2, name="vulnerable_software"),
        SimpleNamespace(category_id=None, name="legacy_finding"),
    ]

    assert views._finding_type_groups(categories, finding_types) == [
        {
            "label": "software",
            "types": [SimpleNamespace(category_id=2, name="vulnerable_software")],
        },
        {
            "label": "lifecycle",
            "types": [SimpleNamespace(category_id=1, name="windows_servicing_eol")],
        },
        {
            "label": "Other",
            "types": [SimpleNamespace(category_id=None, name="legacy_finding")],
        },
    ]


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


def test_findings_queue_template_exposes_device_csv_and_grouped_types():
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert "{{ affected_device_count }} devices" in template
    assert "format=devices_csv" in template
    assert "Issues CSV" in template
    assert "Shown issues CSV" not in template
    assert "<optgroup" in template
    assert "Manage selected" in template
    assert "bulk-action" in template
    assert "Software policy candidates" in template
    assert "Review decision" in template
    assert "Installed devices" in template
    assert "Current result scope" in template
    assert "result_scope_cards" in template
    assert "card.count }} / {{ card.total" in template
    assert "card.percentage" in template


def test_findings_scope_cards_compare_filtered_counts_with_labeled_baselines():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert "status_scope_qs = qs" in source
    assert "fleet_device_total" in source
    assert "fleet_client_total" in source
    assert "result_scope_cards" in source
    assert '"total_label": total_label' in source


def test_software_policy_candidates_are_not_managed_as_incidents():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert views._SOFTWARE_POLICY_CANDIDATE_TYPES == ("whitelist_suggestion",)
    assert "policy_qs" in source
    assert "actionable_qs" in source
    assert "_policy_candidate_state_action_blocked" in source
    assert "Skipped {policy_count} software policy candidate" in source


def test_findings_queue_csv_includes_windows_servicing_context():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")

    assert '"Operating system"' in source
    assert '"OS release"' in source
    assert '"OS build"' in source
    assert '"Lifecycle cycle"' in source
    assert '"Security support ends"' in source


def test_registered_evidence_group_drilldown_opens_the_full_group():
    finding = SimpleNamespace(
        finding_type=SimpleNamespace(
            name="cross_client_serial", drilldown_evidence_key="serial"
        ),
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


def test_finding_group_filter_requires_the_registry_key():
    assert views._finding_group_lookup(
        finding_type_name="cross_client_serial",
        configured_key="serial",
        requested_key="serial",
        requested_value="AB 123",
    ) == {"finding_details__serial__iexact": "AB 123"}
    assert (
        views._finding_group_lookup(
            finding_type_name="cross_client_serial",
            configured_key="serial",
            requested_key="client_ids",
            requested_value="AB 123",
        )
        is None
    )


def test_device_and_issues_templates_explain_the_drilldown_scope():
    device_template = Path("templates/device_detail.html").read_text(encoding="utf-8")
    findings_template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert "{% finding_drilldown_query f device.id %}" in device_template
    assert "Showing every device with this finding type" in findings_template
    assert "Filtered to the selected device." in findings_template
