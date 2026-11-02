"""PLAN-012 Computer-read reconciliation: offline window, verdict readers, Hudu grain."""

from __future__ import annotations

from pathlib import Path

from apps.core.device_status import (
    get_client_device_status_policy,
    offline_days_sql,
    recent_contact_sql,
    stale_contact_sql,
)

_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")


class _Client:
    def __init__(self, days):
        self.offline_after_days = days


def test_sql_reads_the_client_column_with_the_tenant_default():
    sql = offline_days_sql("v.client_id", 7)
    assert "oc.offline_after_days" in sql and "oc.id = v.client_id" in sql
    assert sql.endswith(", 7)")
    recent = recent_contact_sql("v.last_contact_at", "v.client_id", 7)
    assert recent.startswith("v.last_contact_at >= NOW() - make_interval(days => ")
    stale = stale_contact_sql("v.last_contact_at", "v.client_id", 7)
    assert stale.startswith("(v.last_contact_at IS NULL OR NOT ")


def test_client_policy_replaces_only_the_offline_days(monkeypatch):
    from apps.core import device_status

    monkeypatch.setattr(
        device_status,
        "get_device_status_policy",
        lambda tenant_id=1: {"active_device_days": 7, "retire_review_days": 30},
    )
    assert get_client_device_status_policy(_Client(3))["active_device_days"] == 3
    assert get_client_device_status_policy(_Client(None))["active_device_days"] == 7
    assert get_client_device_status_policy(None)["retire_review_days"] == 30


def test_no_operations_fleet_reader_uses_only_the_tenant_value():
    # Fleet-wide readers must go through the shared helpers; client-scoped
    # readers receive the client's own policy before formatting the interval.
    assert '"offline_after_days": row[12]' in _VIEWS
    assert 'row.get("offline_after_days") or active_device_days' in _VIEWS
    assert _VIEWS.count("get_client_device_status_policy(") == 1
    assert "v.last_contact_at >= NOW() - INTERVAL '{active_device_days} days'" not in _VIEWS
    assert "sd.last_contact_at >= NOW() - INTERVAL '{active_device_days} days'" not in _VIEWS


def test_client_missing_drilldown_reads_stored_verdicts():
    # PLAN-012 item 2: the requirement authority is device_requirement_state.
    start = _VIEWS.index("def org_devices(")
    body = _VIEWS[start : _VIEWS.index("@login_required", start)]
    assert "operations.device_requirement_state" in body
    assert "device_agent_presence_current" not in body


def test_computer_requirement_rows_read_stored_verdicts():
    start = _VIEWS.index("def _coverage_policy_rows(")
    body = _VIEWS[start : _VIEWS.index("def _raw_json_object(", start)]
    assert "operations.device_requirement_state" in body
    assert "requirement_profile_items" not in body
    assert "coverage_requirements" not in body


def test_computer_source_records_list_a_multi_card_hudu_asset_once():
    # v_cmdb_inventory_evidence_current has one row per relayed card.
    start = _VIEWS.index("def _device_source_records(")
    body = _VIEWS[start : _VIEWS.index("def _device_process_monitors(", start)]
    assert "LEFT JOIN LATERAL" in body and "LIMIT 1" in body
    assert "LEFT JOIN operations.v_cmdb_inventory_evidence_current hudu" not in body
