"""Shared disposable PostgreSQL fixtures for PLAN-017 Phase 2 checks.

These checks live outside the ordinary suite. Run from the repository root:

    RUN_POSTGRES_INTEGRATION_TESTS=1 .venv/Scripts/python.exe -m pytest \
        docs/records/PLAN-017-phase-2/checks -q

Reproductions assert the *current* behavior a finding describes, so a passing
reproduction means the finding was reproduced, not that the behavior is right.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime

import psycopg
import pytest

# Placeholder settings, as in ingest/tests/test_jobs_worker_drain.py, so
# modules importing ingest.config load without a real environment.
for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 4))


def migration_function_sql(migration: str, function: str) -> str:
    """One CREATE FUNCTION statement, read verbatim from a migration file."""
    path = os.path.join(REPO_ROOT, "operations/apps/core/migrations", migration)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(
        rf"CREATE (?:OR REPLACE )?FUNCTION operations\.{function}\(.*?"
        r"\bAS (\$\w*\$).*?\1;",
        text,
        re.S,
    )
    assert match, f"{function} not found in {migration}"
    return match.group(0)

# Observation tables copied from ingest/tests/test_observation_dual_write_postgres.py
# (the repository's existing shared-contract fixture). Fidelity notes are in
# docs/records/PLAN-017-phase-2-results.md.
OBSERVATION_SCHEMA = """
CREATE TABLE operations.source_bindings (
    id uuid PRIMARY KEY,
    tenant_id bigint NOT NULL,
    source_instance_id uuid NOT NULL
);
CREATE TABLE operations.observation_snapshot_runs (
    run_id uuid PRIMARY KEY,
    tenant_id bigint NOT NULL,
    source_binding_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    snapshot_scope text NOT NULL,
    snapshot_at timestamptz NOT NULL,
    run_started_at timestamptz NULL,
    is_complete_snapshot boolean NULL,
    status text NOT NULL,
    expected_rows integer NOT NULL,
    written_rows integer NOT NULL,
    failed_rows integer NOT NULL,
    error text NOT NULL,
    completed_at timestamptz NULL,
    observed_identity_count integer NOT NULL,
    observed_identity_digest bytea NULL
);
CREATE TABLE operations.entity_observation_current (
    observation_id uuid PRIMARY KEY,
    tenant_id bigint NOT NULL,
    source_binding_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    last_seen_binding_id uuid NULL,
    external_namespace text NOT NULL DEFAULT '',
    parent_external_namespace text NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '',
    external_id text NOT NULL DEFAULT '',
    collector_instance_id uuid NOT NULL,
    client_id uuid NULL,
    device_id uuid NULL,
    entity_type text NOT NULL,
    parent_source_key text NOT NULL DEFAULT '',
    entity_key text NOT NULL,
    platform text NOT NULL,
    subplatform text NOT NULL,
    observed_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    last_received_at timestamptz NOT NULL,
    active boolean NOT NULL,
    withdrawn_at timestamptz NULL,
    snapshot_scope text NOT NULL,
    last_snapshot_run_id uuid NULL,
    raw_data jsonb NOT NULL,
    canonical_data jsonb NOT NULL,
    raw_hash bytea NULL,
    material_hash bytea NOT NULL,
    hash_algorithm_version smallint NOT NULL,
    material_projection_version smallint NOT NULL DEFAULT 1,
    batch_id uuid NOT NULL,
    collector_version text NOT NULL,
    schema_version smallint NOT NULL,
    CONSTRAINT uq_obs_current_identity
        UNIQUE (tenant_id, source_binding_id, entity_type,
                parent_source_key, entity_key),
    UNIQUE (tenant_id, source_instance_id, external_namespace,
            parent_external_namespace, parent_external_id, external_id)
);
CREATE TABLE operations.entity_observation_history (
    id uuid PRIMARY KEY,
    tenant_id bigint NOT NULL,
    source_binding_id uuid NOT NULL,
    source_instance_id uuid NOT NULL,
    last_seen_binding_id uuid NULL,
    external_namespace text NOT NULL DEFAULT '',
    parent_external_namespace text NOT NULL DEFAULT '',
    parent_external_id text NOT NULL DEFAULT '',
    external_id text NOT NULL DEFAULT '',
    collector_instance_id uuid NOT NULL,
    client_id uuid NULL,
    device_id uuid NULL,
    entity_type text NOT NULL,
    platform text NOT NULL,
    parent_source_key text NOT NULL DEFAULT '',
    entity_key text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_to timestamptz NULL,
    last_seen_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    material_data jsonb NOT NULL,
    material_hash bytea NOT NULL,
    hash_algorithm_version smallint NOT NULL,
    material_projection_version smallint NOT NULL DEFAULT 1,
    active boolean NOT NULL,
    closed_by_snapshot_run_id uuid NULL
);
CREATE UNIQUE INDEX uq_obs_hist_open_identity
    ON operations.entity_observation_history
       (tenant_id, source_binding_id, entity_type,
        parent_source_key, entity_key)
    WHERE effective_to IS NULL;
CREATE UNIQUE INDEX uq_test_history_stable
    ON operations.entity_observation_history
       (tenant_id, source_instance_id, external_namespace,
        parent_external_namespace, parent_external_id, external_id)
    WHERE effective_to IS NULL;
"""


@pytest.fixture(scope="session")
def postgres_dsn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_INTEGRATION_TESTS=1 to start a disposable Postgres container"
        )
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        yield container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )


@pytest.fixture
def obs_conn(postgres_dsn):
    """A fresh `operations` observation schema on its own connection."""
    with psycopg.connect(postgres_dsn) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS operations CASCADE")
            cur.execute("CREATE SCHEMA operations")
            cur.execute(OBSERVATION_SCHEMA)
        yield conn


def observation_row(
    binding_id: uuid.UUID,
    instance_id: uuid.UUID,
    run_id: uuid.UUID,
    observed_at: datetime,
    *,
    external_id: str,
    namespace: str = "device",
    scope: str = "Test",
    entity_type: str = "agent.test",
) -> dict:
    return {
        "observation_id": uuid.uuid4(),
        "tenant_id": 1,
        "source_binding_id": binding_id,
        "source_instance_id": instance_id,
        "last_seen_binding_id": binding_id,
        "external_namespace": namespace,
        "parent_external_namespace": "",
        "parent_external_id": "",
        "external_id": external_id,
        "collector_instance_id": uuid.uuid4(),
        "client_id": None,
        "device_id": None,
        "entity_type": entity_type,
        "parent_source_key": "",
        "entity_key": f"{namespace}:{external_id}",
        "platform": "Test",
        "subplatform": "",
        "observed_at": observed_at,
        "last_seen_at": observed_at,
        "last_received_at": observed_at,
        "active": True,
        "withdrawn_at": None,
        "snapshot_scope": scope,
        "last_snapshot_run_id": run_id,
        "raw_data": {"record": external_id},
        "canonical_data": {"hostname": f"host-{external_id}"},
        "raw_hash": b"r" * 32,
        "batch_id": uuid.uuid4(),
        "collector_version": "",
        "schema_version": 1,
    }
