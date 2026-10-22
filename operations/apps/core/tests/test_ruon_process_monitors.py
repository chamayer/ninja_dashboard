"""R-U-ON process monitors are shown on their machine's source record."""

from __future__ import annotations

import importlib
from pathlib import Path

from django.template.loader import get_template

_ROOT = Path(__file__).resolve().parents[3]
_VIEWS = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
_DETAIL = (_ROOT / "templates" / "device_detail.html").read_text(encoding="utf-8")
_MIGRATION = importlib.import_module("apps.core.migrations.0338_ruon_process_monitors")
_PREVIOUS_VIEW = importlib.import_module(
    "apps.core.migrations.0334_safe_observation_identity_metadata"
)


def test_migration_follows_the_previous_one():
    assert _MIGRATION.Migration.dependencies == [
        ("operations", "0337_client_candidate_renamed_status")
    ]


def test_the_view_only_gains_a_guarded_monitor_list():
    sql = _MIGRATION.FORWARD_SQL
    view = sql.split("CREATE OR REPLACE VIEW", 1)[1].split("ALTER VIEW", 1)[0]
    previous = _PREVIOUS_VIEW.FORWARD_SQL.split("CREATE OR REPLACE VIEW", 1)[1].split(
        "ALTER VIEW", 1
    )[0]
    assert view.startswith(previous.split(" AS hudu_company_id", 1)[0])
    assert "jsonb_typeof(observation.canonical_data->'process_monitors') = 'array'" in view
    assert "AS process_monitors" in view
    # Raw payloads stay restricted: only the existing Hudu company id reads them.
    assert view.count("raw_data") == 1
    for statement in (
        "OWNER TO operations_view_owner",
        "REVOKE ALL ON operations.v_entity_observation_admin_metadata",
        "GRANT SELECT ON operations.v_entity_observation_admin_metadata",
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE",
    ):
        assert statement in sql
    assert "entity_types" not in sql


def test_the_computer_page_shows_monitors_in_the_source_record_row():
    assert "def _device_process_monitors(cur, device_id)" in _VIEWS
    assert "monitors.get(str(row[0]), [])" in _VIEWS
    # Every unpacking of the extended rows names the new field.
    assert "record_lifecycle, _process_monitors in observations" in _VIEWS
    assert "record_lifecycle, process_monitors in observations %}" in _DETAIL
    assert "Process monitor: {{ monitor.name }}" in _DETAIL
    get_template("device_detail.html")
