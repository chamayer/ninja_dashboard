from pathlib import Path
from types import SimpleNamespace

from apps.core import views


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
    assert "result_scope_counts.devices" in template
    assert "result_scope_counts.clients" in template


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
