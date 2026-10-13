from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingest import software_readiness as sr
from shared.conditions.policy import parse_profile

_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
PROFILE = parse_profile(
    json.loads((_ROOT / "shared" / "conditions" / "profile.json").read_text(encoding="utf-8"))
)
TYPES = [(1, "vulnerable_software"), (2, "whitelist_suggestion")]


def _rows(devices, contacts=None):
    return sr.compute(
        tenant_id=1, devices=devices, contacts=contacts or {}, finding_types=TYPES,
        profile=PROFILE, now=NOW, offline_days=35,
    )


def _by_type(rows):
    return {(row[1], row[2]): row for row in rows}


def test_one_row_per_device_and_type_with_every_column():
    rows = _rows([("a", True, False), ("b", True, False)])
    assert len(rows) == 4
    assert all(len(row) == len(sr.READINESS_COLUMNS.split(",")) == 11 for row in rows)
    assert {row[3] for row in rows} == {PROFILE.version}


def test_identity_conflict_blocks_identity_gated_types():
    row = _by_type(_rows([("a", True, True)]))[("a", 1)]
    assert row[5] == "blocked"
    assert row[6] is False and row[7] is False
    assert "identity:unsettled_group" in row[8]


def test_settled_identity_with_recent_contact_is_eligible():
    rows = _by_type(_rows([("a", True, False)], {"a": NOW - timedelta(days=1)}))
    assert rows[("a", 1)][5] == "eligible"
    assert rows[("a", 1)][7] is True


def test_unmeasured_identity_is_unknown_never_ready():
    row = _by_type(_rows([("a", False, False)]))[("a", 1)]
    assert row[5] == "unknown"
    assert row[7] is False


def test_types_without_device_rules_do_not_depend_on_the_device():
    rows = _by_type(_rows([("a", False, True)]))
    assert rows[("a", 2)][5] == "eligible"  # whitelist_suggestion has no device rules


def test_identity_is_loaded_for_the_fleet_in_one_set_based_query():
    assert "ANY(" not in sr.IDENTITY_SQL
    assert "jsonb_array_elements_text" in sr.IDENTITY_SQL
    assert "identity_conflict" in sr.IDENTITY_SQL
    assert "condition_reviewed_distinct" in sr.IDENTITY_SQL


def test_refresh_replaces_the_tenant_rows_and_removes_stale_ones():
    source = (_ROOT / "ingest" / "software_readiness.py").read_text(encoding="utf-8")
    body = source[source.index("def refresh(") :]
    assert "load_active_profile(cur)" in body
    assert "COPY software_device_readiness_next" in body
    assert "ON CONFLICT (tenant_id, device_id, finding_type_id) DO UPDATE" in body
    assert "DELETE FROM operations.software_device_readiness" in body


def test_migration_creates_a_tenant_isolated_derived_table():
    sql = (
        _ROOT / "operations" / "apps" / "core" / "migrations"
        / "0282_software_device_readiness.py"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE operations.software_device_readiness" in sql
    assert "PRIMARY KEY (tenant_id, device_id, finding_type_id)" in sql
    assert "REFERENCES operations.devices(tenant_id, id) ON DELETE CASCADE" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "GRANT INSERT, UPDATE, DELETE ON operations.software_device_readiness TO ninja_ingest" in sql
    assert "0281_jobs_wait_reason_names_interrupted_holder" in sql
