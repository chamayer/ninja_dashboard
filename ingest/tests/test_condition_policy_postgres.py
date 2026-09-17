"""PostgreSQL behavior for the condition policy registry migration.

Run with ``RUN_POSTGRES_INTEGRATION_TESTS=1``. The fixture is disposable and
does not connect to a configured environment.
"""

from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

_MIGRATIONS = Path(__file__).resolve().parents[2] / "operations" / "apps" / "core" / "migrations"
_PROFILE = Path(__file__).resolve().parents[2] / "shared" / "conditions" / "profile.json"
_ROLE_PASSWORD = "probe"


def _forward_sql() -> str:
    return _migration_sql("0161_live_condition_contract.py")


def _migration_sql(filename: str) -> str:
    spec = importlib.util.spec_from_file_location("condition_policy_migration", _MIGRATIONS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load condition policy migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FORWARD_SQL


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "condition_policy_migration", _MIGRATIONS / "0161_live_condition_contract.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load condition policy migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration(filename: str):
    spec = importlib.util.spec_from_file_location("condition_policy_migration", _MIGRATIONS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load condition policy migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pg():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        parsed = urlparse(
            container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        )
        admin_dsn = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}{parsed.path}"

        def role_dsn(role: str) -> str:
            return (
                f"postgresql://{role}:{_ROLE_PASSWORD}@{parsed.hostname}:{parsed.port}{parsed.path}"
            )

        with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION pgcrypto")
            cur.execute("CREATE SCHEMA operations")
            cur.execute(
                "CREATE TABLE operations.tenants (id bigint PRIMARY KEY, slug text NOT NULL)"
            )
            cur.execute(
                """CREATE TABLE operations.finding_types (
                    id smallint PRIMARY KEY, name text NOT NULL UNIQUE
                )"""
            )
            for index, definition in enumerate(
                json.loads(_PROFILE.read_text(encoding="utf-8"))["definitions"], 1
            ):
                cur.execute(
                    "INSERT INTO operations.finding_types (id, name) VALUES (%s, %s)",
                    (index, definition["name"]),
                )
            cur.execute("INSERT INTO operations.tenants (id, slug) VALUES (1, 'test')")
            cur.execute("INSERT INTO operations.tenants (id, slug) VALUES (2, 'other')")
            for role in (
                "operations_migrate",
                "operations_app",
                "operations_readonly",
                "metabase_ro",
                "ninja_ingest",
            ):
                cur.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{_ROLE_PASSWORD}'")
                cur.execute(f"GRANT CONNECT ON DATABASE {parsed.path.lstrip('/')} TO {role}")
            cur.execute(
                "GRANT USAGE ON SCHEMA operations TO operations_migrate, operations_app, ninja_ingest"
            )
            cur.execute(_forward_sql())
            cur.execute(
                "GRANT SELECT ON operations.finding_types, operations.tenants TO operations_migrate"
            )
            cur.execute(_migration_sql("0162_harden_condition_policy_authority.py"))
            cur.execute(_migration_sql("0163_condition_assessment_policy_digest.py"))

        yield {
            "admin": admin_dsn,
            "app": role_dsn("operations_app"),
            "ingest": role_dsn("ninja_ingest"),
        }


def test_policy_creation_activation_and_runtime_permissions(pg):
    profile = json.loads(_PROFILE.read_text(encoding="utf-8"))
    migration = _migration_module()
    with psycopg.connect(pg["admin"], autocommit=True) as conn, conn.cursor() as cur:
        finding_types = {}
        cur.execute("SELECT id, name FROM operations.finding_types")
        for finding_type_id, name in cur.fetchall():
            finding_types[name] = SimpleNamespace(pk=finding_type_id)

        class _FindingType:
            class objects:
                @staticmethod
                def in_bulk(names, field_name):
                    assert field_name == "name"
                    return {name: finding_types[name] for name in names}

        class _Apps:
            @staticmethod
            def get_model(app_label, model_name):
                assert (app_label, model_name) == ("operations", "FindingType")
                return _FindingType

        migration.seed_policies(_Apps, SimpleNamespace(connection=conn))
        _load_migration("0164_policy_defined_issue_categories.py").promote_categories(
            None, SimpleNamespace(connection=conn)
        )
        cur.execute(_migration_sql("0165_govern_condition_policy_activation.py"))
        cur.execute(_migration_sql("0166_condition_assessment_integrity.py"))
        cur.execute(_migration_sql("0167_reviewed_distinct_conditions.py"))
        cur.execute(_migration_sql("0169_align_condition_reviewer_ids.py"))
    with psycopg.connect(pg["app"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET operations.tenant_id = '1'")
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute(
                "SELECT operations.activate_condition_policy_version(%s)", (profile["version"],)
            )
        cur.execute(
            "SELECT operations.review_condition_policy_version(%s,%s,%s,%s::jsonb)",
            (profile["version"], 1, "Initial policy review", json.dumps({"valid": True})),
        )
        cur.execute(
            "SELECT operations.activate_condition_policy_version(%s)", (profile["version"],)
        )
        cur.execute(
            "SELECT count(*) FROM operations.condition_policies WHERE policy_version = %s",
            (profile["version"],),
        )
        assert cur.fetchone()[0] == len(profile["definitions"])
        cur.execute("SELECT count(*) FROM operations.condition_policy_versions WHERE active")
        assert cur.fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "UPDATE operations.condition_policy_versions SET digest = %s",
                ("b" * 64,),
            )
        assessment_id = uuid4()
        cur.execute(
            """INSERT INTO operations.condition_assessments
                (tenant_id, row_kind, finding_id, participant_kind, participant_id,
                 participant_role, condition_identity, policy_version, policy_digest,
                 coverage, response, reevaluation_key)
                VALUES (1, 'entity', %s, 'device', %s, 'affected', 'identity', %s, %s,
                        '{}'::jsonb,
                        '{"may_evaluate": true, "may_notify": true,
                          "may_execute": true, "may_clear": true}'::jsonb,
                        'activation-before-replacement')""",
            (
                assessment_id,
                uuid4(),
                profile["version"],
                "5e9b47350aabfc45b6cd21fea2bfd6e591ec9826886187ddfcfe0d6a7a031c40",
            ),
        )
        replacement = deepcopy(profile)
        replacement["version"] = "conditions-shadow-2"
        cur.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (replacement["version"], "c" * 64, json.dumps(replacement)),
        )
        cur.execute(
            "SELECT operations.review_condition_policy_version(%s,%s,%s,%s::jsonb)",
            (replacement["version"], 1, "Replacement policy review", json.dumps({"valid": True})),
        )
        cur.execute(
            "SELECT operations.activate_condition_policy_version(%s)",
            (replacement["version"],),
        )
        cur.execute("SELECT version FROM operations.condition_policy_versions WHERE active")
        assert cur.fetchone()[0] == replacement["version"]
        cur.execute(
            "SELECT response->>'may_notify', response->>'may_execute', "
            "response->>'may_clear', currentness->>'invalidated_reason' "
            "FROM operations.condition_assessments WHERE finding_id = %s",
            (assessment_id,),
        )
        assert cur.fetchone() == ("false", "false", "false", "policy_activated")
        cur.execute(
            "SELECT operations.activate_condition_policy_version(%s)",
            (profile["version"],),
        )
        cur.execute("SELECT count(*) FROM operations.condition_policy_versions WHERE active")
        assert cur.fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM operations.condition_policies")


def test_runtime_assessments_are_tenant_scoped_and_participants_are_normalized(pg):
    finding_id = uuid4()
    with psycopg.connect(pg["ingest"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET operations.tenant_id = '1'")
        cur.execute("DELETE FROM operations.condition_assessments WHERE tenant_id = 1")
        cur.execute("DELETE FROM operations.condition_participants WHERE tenant_id = 1")
        cur.execute(
            """INSERT INTO operations.condition_assessments
                (tenant_id, row_kind, finding_id, participant_kind, participant_id,
                     participant_role, condition_identity, policy_version,
                     policy_digest, coverage, response, reevaluation_key)
                VALUES (1, 'entity', %s, 'device', %s, 'affected',
                        'identity', 'conditions-shadow-1', %s, '{}'::jsonb, '{}'::jsonb, 'run-1'),
                       (1, 'entity', %s, 'software_version', %s, 'affected',
                        'identity', 'conditions-shadow-1', %s, '{}'::jsonb, '{}'::jsonb, 'run-1')""",
            (
                finding_id, uuid4(),
                "5e9b47350aabfc45b6cd21fea2bfd6e591ec9826886187ddfcfe0d6a7a031c40",
                finding_id, uuid4(),
                "5e9b47350aabfc45b6cd21fea2bfd6e591ec9826886187ddfcfe0d6a7a031c40",
            ),
        )
        cur.execute(
            "SELECT count(*), count(policy_digest), min(policy_digest) "
            "FROM operations.v_condition_assessment_current"
        )
        count, digest_count, minimum_digest = cur.fetchone()
        assert count == 2
        assert digest_count == 2
        assert minimum_digest == "5e9b47350aabfc45b6cd21fea2bfd6e591ec9826886187ddfcfe0d6a7a031c40"
        cur.execute("SET operations.tenant_id = '2'")
        cur.execute("SELECT count(*) FROM operations.v_condition_assessment_current")
        assert cur.fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM operations.v_condition_assessment_current")


def test_policy_storage_grants_separate_runtime_reads_and_assessment_writes(pg):
    with psycopg.connect(pg["admin"], autocommit=True) as conn, conn.cursor() as cur:
        for role in ("operations_app", "ninja_ingest", "operations_readonly", "metabase_ro"):
            for table in ("condition_policy_versions", "condition_policies"):
                cur.execute(
                    "SELECT has_table_privilege(%s, %s, 'SELECT')",
                    (role, f"operations.{table}"),
                )
                assert cur.fetchone()[0] is True
        for role in ("operations_app", "ninja_ingest"):
            for table in ("condition_assessments", "condition_participants"):
                cur.execute(
                    "SELECT has_table_privilege(%s, %s, 'INSERT,UPDATE,DELETE')",
                    (role, f"operations.{table}"),
                )
                assert cur.fetchone()[0] is True
        for role in ("operations_readonly", "metabase_ro"):
            for table in ("condition_assessments", "condition_participants"):
                cur.execute(
                    "SELECT has_table_privilege(%s, %s, 'INSERT')",
                    (role, f"operations.{table}"),
                )
                assert cur.fetchone()[0] is False
        cur.execute(
            "SELECT has_function_privilege(%s, 'operations.create_condition_policy_version(text,text,jsonb)', 'EXECUTE')",
            ("operations_app",),
        )
        assert cur.fetchone()[0] is True


def test_participant_reconciliation_removes_stale_scope_and_assessment_rows(pg):
    finding_id = uuid4()
    old_device = uuid4()
    new_device = uuid4()
    with psycopg.connect(pg["ingest"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET operations.tenant_id = '1'")
        cur.execute(
            "SELECT version, digest FROM operations.condition_policy_versions WHERE active"
        )
        policy_version, policy_digest = cur.fetchone()
        cur.execute(
            """INSERT INTO operations.condition_assessments
                (tenant_id, row_kind, finding_id, participant_kind, participant_id,
                 participant_role, condition_identity, policy_version, policy_digest,
                 coverage, response, reevaluation_key)
                VALUES (1, 'entity', %s, 'device', %s, 'affected', 'identity', %s, %s,
                        '{}'::jsonb, '{}'::jsonb, 'merge-before')""",
            (finding_id, old_device, policy_version, policy_digest),
        )
        cur.execute(
            """INSERT INTO operations.condition_participants
                (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
                VALUES (1, 'entity', %s, 'device', %s, 'affected')""",
            (finding_id, old_device),
        )
        cur.execute(
            """SELECT operations.reconcile_condition_participants(
                1, 'entity', %s, %s::jsonb)""",
            (
                finding_id,
                json.dumps([{
                    "kind": "device",
                    "reference": str(new_device),
                    "role": "affected",
                    "tenant_id": 1,
                }]),
            ),
        )
        cur.execute(
            """SELECT participant_id FROM operations.condition_participants
                WHERE finding_id = %s AND participant_kind = 'device'""",
            (finding_id,),
        )
        assert cur.fetchall() == [(new_device,)]
        cur.execute(
            """SELECT participant_id FROM operations.condition_assessments
                WHERE finding_id = %s AND participant_kind = 'device'""",
            (finding_id,),
        )
        assert cur.fetchall() == []


def test_condition_scope_advisory_lock_serializes_concurrent_reconciliation(pg):
    finding_id = uuid4()
    lock_sql = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
    first = psycopg.connect(pg["admin"], autocommit=False)
    second = psycopg.connect(pg["admin"], autocommit=False)
    try:
        with first.cursor() as cur:
            cur.execute(lock_sql, (f"1:entity:{finding_id}",))
        with second.cursor() as cur:
            cur.execute("SET statement_timeout = '100ms'")
            with pytest.raises(psycopg.errors.QueryCanceled):
                cur.execute(lock_sql, (f"1:entity:{finding_id}",))
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
