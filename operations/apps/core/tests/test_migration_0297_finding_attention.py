"""Migration 0297: stored finding attention, one rule, one writer."""

from __future__ import annotations

import importlib
from pathlib import Path

_MIGRATION = importlib.import_module("apps.core.migrations.0297_finding_attention")
_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")


def test_depends_on_the_slim_policy_and_adds_both_columns_to_the_model_state():
    assert _MIGRATION.Migration.dependencies == [("operations", "0296_slim_condition_policy")]
    wrapper = _MIGRATION.Migration.operations[0]
    assert {op.name for op in wrapper.state_operations} == {"attention", "attention_at"}


def test_the_rule_exists_once_and_refresh_is_the_only_writer():
    sql = _MIGRATION.FORWARD_SQL
    assert sql.count("CREATE OR REPLACE FUNCTION operations.compute_finding_attention") == 1
    assert sql.count("SET attention = ") == 1
    assert "CHECK (attention IN ('needs_action', 'blocked', 'pending', 'covered'))" in sql


def test_status_changes_refresh_the_finding_and_what_it_covers():
    sql = _MIGRATION.FORWARD_SQL
    assert "AFTER UPDATE OF status ON operations.findings" in sql
    assert "WHEN (OLD.status IS DISTINCT FROM NEW.status)" in sql
    assert "AFTER INSERT ON operations.findings" in sql
    assert "ft.covered_by ? c.type_name" in sql
    assert "WITH RECURSIVE" in sql
    assert "pg_trigger_depth() > 1" in sql


def test_pause_is_not_part_of_the_stored_rule():
    assert "snoozed_until" not in _MIGRATION.FORWARD_SQL


def test_the_drift_table_keeps_what_was_stored_and_when_under_row_security():
    sql = _MIGRATION.FORWARD_SQL
    for column in ("stored_attention", "computed_attention", "found_at"):
        assert column in sql
    assert "FORCE ROW LEVEL SECURITY" in sql


def test_the_fill_runs_in_tenant_context():
    assert "set_config('operations.tenant_id', '1', TRUE)" in _MIGRATION.FILL_SQL
    assert "refresh_finding_attention" in _MIGRATION.FILL_SQL


def test_issues_reads_the_stored_value_only_behind_the_setting():
    assert "if settings.ISSUES_STORED_ATTENTION:" in _VIEWS
    assert "response_ids = _stored_response_ids(assessment_ids)" in _VIEWS
    assert "response_ids = _condition_response_ids(assessment_ids)" in _VIEWS
