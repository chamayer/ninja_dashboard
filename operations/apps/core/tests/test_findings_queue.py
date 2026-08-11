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
        return [("device-1", "host-1", "Client A", ["windows_servicing_eol"])]


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
            "finding_types": ["windows_servicing_eol"],
        }
    ]


def test_findings_queue_template_exposes_device_csv_and_grouped_types():
    template = Path("templates/findings_queue.html").read_text(encoding="utf-8")

    assert "{{ affected_device_count }} devices" in template
    assert "format=devices_csv" in template
    assert "<optgroup" in template
    assert "Bulk actions" in template
    assert "bulk-action" in template
