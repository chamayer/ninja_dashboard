"""Small PostgreSQL fixtures verify matcher difference publication and its consumers."""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager

import psycopg
import pytest

from operations.apps.core.tests.test_migration_0306_postgres import (
    SCHEMA as HISTORY_SCHEMA,
)

for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest.intel import matcher  # noqa: E402

SCHEMA = """
CREATE ROLE metabase_ro NOLOGIN;
CREATE SCHEMA catalog;
CREATE SCHEMA intel;
CREATE TABLE operations.tenants (id bigint PRIMARY KEY);
INSERT INTO operations.tenants VALUES (1), (2);
CREATE TABLE catalog.products (id bigint PRIMARY KEY, canonical_name text);
CREATE TABLE catalog.software_versions (id bigint PRIMARY KEY, product_id bigint, version text);
CREATE TABLE operations.software_installations_current (
    tenant_id bigint, software_version_id bigint, deleted_at timestamptz, stale_since timestamptz
);
CREATE TABLE intel.cpes (cpe23 text PRIMARY KEY, vendor text, product text, version text);
CREATE TABLE intel.cves (cve_id text PRIMARY KEY, affected_cpes jsonb);
CREATE SEQUENCE operations.cve_match_id_seq;
ALTER TABLE operations.cve_match ALTER COLUMN id
    SET DEFAULT nextval('operations.cve_match_id_seq');
ALTER TABLE operations.cve_match ALTER COLUMN matched_at SET DEFAULT now();
CREATE UNIQUE INDEX cve_match_scope_idx ON operations.cve_match
    (tenant_id, canonical_name, software_version_id, cve_id, match_kind) NULLS NOT DISTINCT;
ALTER TABLE operations.cve_match ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.cve_match FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.cve_match
    USING (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint)
    WITH CHECK (tenant_id = nullif(current_setting('operations.tenant_id', true), '')::bigint);
GRANT USAGE ON SCHEMA catalog, intel TO ninja_ingest;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog, intel TO ninja_ingest;
GRANT SELECT ON operations.software_installations_current TO ninja_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.cve_match TO ninja_ingest;
GRANT USAGE, SELECT ON SEQUENCE operations.cve_match_id_seq TO ninja_ingest;
"""


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 for disposable PostgreSQL coverage"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(HISTORY_SCHEMA)
            foundation = importlib.import_module(
                "operations.apps.core.migrations.0306_change_history_foundation"
            )
            with conn.transaction():
                conn.execute("SET LOCAL ROLE operations_migrate")
                conn.execute(foundation.FOUNDATION_SQL)
            conn.execute(SCHEMA)
            for name in (
                "0250_software_reclassification_targets",
                "0277_software_reclassification_target_cursor",
                "0349_software_target_generation",
            ):
                conn.execute(
                    importlib.import_module(
                        f"operations.apps.core.migrations.{name}"
                    ).FORWARD_SQL
                )
            yield conn


@pytest.fixture
def conn(database, monkeypatch):
    database.execute("""
        TRUNCATE operations.cve_match, operations.cve_match_change_history,
                 operations.change_actions, operations.software_reclassification_targets,
                 operations.software_installations_current, catalog.products,
                 catalog.software_versions, intel.cpes, intel.cves CASCADE;
        INSERT INTO catalog.products VALUES (1, 'Acme Widget');
        INSERT INTO catalog.software_versions VALUES (101, 1, '1.0'), (202, 1, '2.0');
        INSERT INTO operations.software_installations_current
            VALUES (1, 101, NULL, NULL), (1, 202, NULL, NULL);
        INSERT INTO intel.cpes VALUES
            ('all', 'acme', 'widget', '*'), ('v1', 'acme', 'widget', '1.0'),
            ('v2', 'acme', 'widget', '2.0');
        INSERT INTO intel.cves VALUES
            ('CVE-all', '["all"]'), ('CVE-v1', '["v1"]'), ('CVE-v2', '["v2"]');
    """)

    @contextmanager
    def transaction():
        with database.transaction(), database.cursor() as cur:
            cur.execute("SET LOCAL ROLE ninja_ingest")
            cur.execute("SET LOCAL operations.tenant_id = 1")
            yield cur

    monkeypatch.setattr(matcher.db, "transaction", transaction)
    monkeypatch.setattr(matcher, "_load_hints", lambda: (set(), []))
    return database


def _rows(conn, tenant=1):
    return conn.execute(
        "SELECT ctid::text, id, canonical_name, software_version_id, cve_id, "
        "match_kind, version_range, confidence, matched_at FROM operations.cve_match "
        "WHERE tenant_id = %s ORDER BY cve_id, software_version_id",
        (tenant,),
    ).fetchall()


def _history(conn):
    return conn.execute(
        "SELECT operation, before_values, after_values FROM operations.cve_match_change_history "
        "ORDER BY id"
    ).fetchall()


def _targets(conn):
    return dict(
        conn.execute(
            "SELECT target_key, generation FROM operations.software_reclassification_targets "
            "WHERE consumed_at IS NULL"
        ).fetchall()
    )


@pytest.mark.integration
def test_identical_full_recompute_preserves_rows_ids_timestamps_and_consumers(conn):
    result = matcher._match_and_upsert()
    assert int(result) == 3 and result.material_changed
    # Includes one NULL-version product key, without duplicate wildcard matches.
    assert [(row[3], row[4]) for row in _rows(conn)] == [
        (None, "CVE-all"),
        (101, "CVE-v1"),
        (202, "CVE-v2"),
    ]
    before = (_rows(conn), _history(conn), _targets(conn))
    sequence = conn.execute(
        "SELECT last_value FROM operations.cve_match_id_seq"
    ).fetchone()
    result = matcher._match_and_upsert()
    assert int(result) == 3 and not result.material_changed
    assert (_rows(conn), _history(conn), _targets(conn)) == before
    assert (
        conn.execute("SELECT last_value FROM operations.cve_match_id_seq").fetchone()
        == sequence
    )
    assert _targets(conn) == {"name:acme widget": 1, "version:101": 1, "version:202": 1}


@pytest.mark.integration
@pytest.mark.parametrize(
    "field,value", (("confidence", "medium"), ("version_range", None))
)
def test_additions_removals_and_payload_changes_preserve_survivors_and_queue_deltas(
    conn,
    field,
    value,
):
    matcher._match_and_upsert()
    conn.execute("UPDATE operations.cve_match SET matched_at = '2000-01-01'")
    before = {row[4]: row for row in _rows(conn)}
    conn.execute(
        f"UPDATE operations.cve_match SET {field} = %s WHERE cve_id = 'CVE-all'",
        (value,),
    )
    conn.execute("DELETE FROM intel.cves WHERE cve_id = 'CVE-v1'")
    conn.execute("INSERT INTO intel.cves VALUES ('CVE-new', '[\"v2\"]')")
    assert matcher._match_and_upsert().material_changed
    after = {row[4]: row for row in _rows(conn)}
    assert set(after) == {"CVE-all", "CVE-v2", "CVE-new"}
    assert after["CVE-v2"] == before["CVE-v2"]
    assert after["CVE-all"][1] == before["CVE-all"][1]
    assert after["CVE-all"][6:8] == ("*", "high")
    assert after["CVE-all"][8] > before["CVE-all"][8]
    changes = _history(conn)[3:]
    assert (
        len(changes) == 4
    )  # one removal, one addition and a payload before/after pair
    assert sum(op == "D" for op, _, _ in changes) == 2
    assert _targets(conn) == {"name:acme widget": 2, "version:101": 2, "version:202": 2}


@pytest.mark.integration
@pytest.mark.parametrize(
    "empty_table",
    (
        "operations.software_installations_current",
        "intel.cpes",
        "intel.cves",
    ),
)
def test_empty_input_removes_matches_with_audit_and_targets_once(conn, empty_table):
    matcher._match_and_upsert()
    conn.execute(f"DELETE FROM {empty_table}")
    result = matcher._match_and_upsert()
    assert int(result) == 0 and result.material_changed
    assert not _rows(conn)
    assert [op for op, _, _ in _history(conn)] == ["I"] * 3 + ["D"] * 3
    assert set(_targets(conn).values()) == {2}
    before = (_history(conn), _targets(conn))
    assert not matcher._match_and_upsert().material_changed
    assert (_history(conn), _targets(conn)) == before


@pytest.mark.integration
def test_other_tenant_and_atomic_rollback_are_preserved(conn):
    matcher._match_and_upsert()
    conn.execute("""INSERT INTO operations.cve_match
        (tenant_id, canonical_name, cve_id, match_kind, confidence)
        VALUES (2, 'Other Widget', 'CVE-other', 'cpe_exact', 'high')""")
    other = _rows(conn, 2)
    before = (_rows(conn), _history(conn), _targets(conn))
    conn.execute("DELETE FROM intel.cves WHERE cve_id = 'CVE-v1'")
    # Reject the target write after persistence and audit; all must roll back.
    conn.execute(
        "ALTER TABLE operations.software_reclassification_targets "
        "ADD CONSTRAINT synthetic_generation_limit CHECK (generation = 1)"
    )
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            matcher._match_and_upsert()
    finally:
        conn.execute(
            "ALTER TABLE operations.software_reclassification_targets "
            "DROP CONSTRAINT synthetic_generation_limit"
        )
    assert (_rows(conn), _history(conn), _targets(conn)) == before
    assert matcher._match_and_upsert().material_changed
    assert _rows(conn, 2) == other


def test_run_once_refreshes_safety_even_when_match_membership_is_equal(monkeypatch):
    statements = []
    result = matcher.MaterialCount(3, material_changed=False)
    monkeypatch.setattr(matcher.settings, "INTEL_ENABLED", True)
    monkeypatch.setattr(matcher, "_match_and_upsert", lambda: result)

    @contextmanager
    def record_run(_name):
        yield {}

    class Cursor:
        def execute(self, sql):
            statements.append(sql)

    @contextmanager
    def transaction():
        yield Cursor()

    monkeypatch.setattr(matcher, "record_run", record_run)
    monkeypatch.setattr(matcher.db, "transaction", transaction)
    assert matcher.run_once() is result
    assert statements == ["REFRESH MATERIALIZED VIEW operations.v_software_safety"]
