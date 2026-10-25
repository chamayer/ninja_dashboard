"""Inventory > Source records says what a record is and why it is unlinked (interim, ADR-0044)."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

from django.template.loader import get_template

from apps.core import views

migration = importlib.import_module("apps.core.migrations.0344_source_record_layout_and_url")
restriction = importlib.import_module("apps.core.migrations.0345_restricted_source_layouts")
join_once = importlib.import_module("apps.core.migrations.0346_restricted_layouts_join_once")
_ROOT = Path(__file__).resolve().parents[3]


def _reason(**overrides):
    values = {
        "entity_type": "cmdb.asset",
        "active": True,
        "device_id": None,
        "client_id_known": True,
        "archived": False,
        "link_verdict": "unlinked",
        "proposed_other": False,
    }
    values.update(overrides)
    reason = views._unlinked_reason(**values)
    return reason["key"] if reason else None


def test_each_unlinked_record_gets_one_reason_in_order_of_what_explains_it():
    assert _reason(archived=True, link_verdict="stale") == "archived"
    assert _reason(link_verdict="stale") == "stale"
    assert _reason(client_id_known=False) == "group"
    assert _reason(proposed_other=True) == "asset"
    assert _reason() == "no_match"


def test_attached_withdrawn_and_source_group_records_have_no_reason():
    assert _reason(device_id=uuid.uuid4()) is None
    assert _reason(active=False) is None
    assert _reason(entity_type="org") is None


def test_records_link_to_their_source_where_a_link_is_known():
    stored = "https://hudu.example/a/7"
    assert views._source_record_url("Hudu", "cmdb.asset", "7", stored) == stored
    assert views._source_record_url("Ninja", "agent.rmm", "123", None).endswith(
        "/#/deviceDashboard/123/overview"
    )
    assert views._source_record_url("Ninja", "org", "5", None) == ""
    assert views._source_record_url("SentinelOne", "agent.edr", "9", None) == ""


def test_the_view_appends_layout_and_url_and_stays_read_only():
    sql = " ".join(migration.FORWARD_SQL.split())
    assert (
        sql.index("AS process_monitors,")
        < sql.index("AS source_layout")
        < sql.index("AS source_url")
    )
    assert (
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_entity_observation_admin_metadata"
        in sql
    )
    assert "raw_data->>'hudu_url'" not in sql


def test_the_page_shows_name_group_links_reason_and_issues():
    get_template("source_records.html")
    page = (_ROOT / "templates" / "source_records.html").read_text(encoding="utf-8")
    for fragment in (
        "record.reported_name",
        "record.group_name|default:record.group_id",
        "Open in {{ record.source_name }}",
        "{% url 'entity_admin_detail' record.device_entity_id %}",
        "record.unlinked_reason.label",
        "?subject_id={{ record.device_id }}",
        "about this record",
    ):
        assert fragment in page, fragment


def test_the_reason_filter_and_the_column_name_the_same_reasons():
    assert set(views._UNLINKED_REASON_SQL) == set(views._UNLINKED_REASON_LABELS)
    for key in views._UNLINKED_REASON_SQL:
        assert (
            "observation.device_id IS NULL AND observation.active"
            in views._UNLINKED_REASON_SQL[key]
        )
    page = (_ROOT / "templates" / "source_records.html").read_text(encoding="utf-8")
    assert '<select name="layout">' in page and '<select name="reason">' in page
    # Paginated: the browser filter row would only see one page.
    assert "data-sortable data-server-table" in page


def test_restricted_layouts_stay_collected_but_show_no_name_serial_or_link():
    assert restriction.SETTINGS == {"layouts": ["Credit Card"]}
    sql = " ".join(restriction.FORWARD_SQL.split())
    for column in (
        "canonical_hostname",
        "reported_name",
        "canonical_serial",
        "vm_uuid",
        "source_url",
    ):
        end = sql.index(f"AS {column}")
        assert "NOT restricted.is_restricted" in sql[sql.rindex("CASE WHEN", 0, end) : end], column
    assert "restriction.evaluator_name = 'restricted_source_layouts'" in sql
    assert sql.index("AS source_url") < sql.index("AS restricted")
    page = (_ROOT / "templates" / "source_records.html").read_text(encoding="utf-8")
    assert "{% if record.restricted %}" in page


def test_restricted_layouts_are_read_once_per_query():
    sql = " ".join(join_once.FORWARD_SQL.split())
    assert "LEFT JOIN operations.evaluator_config restriction" in sql
    assert "EXISTS (SELECT 1 FROM operations.evaluator_config" not in sql
    assert (
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_entity_observation_admin_metadata"
        in sql
    )
    for column in (
        "canonical_hostname",
        "reported_name",
        "canonical_serial",
        "vm_uuid",
        "source_url",
    ):
        end = sql.index(f"AS {column}")
        assert "NOT restricted.is_restricted" in sql[sql.rindex("CASE WHEN", 0, end) : end], column
