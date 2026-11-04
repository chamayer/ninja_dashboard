"""Exercise the production ownership/queue functions on tiny concurrent fixtures."""

import ast
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID

import psycopg
import pytest

from shared.findings_contract import guard_findings_writes

ROOT = Path(__file__).resolve().parents[2]
A, B, CLIENT = (UUID(int=i) for i in (1, 2, 3))


def function(migration, name):
    tree = ast.parse((ROOT / "operations/apps/core/migrations" / migration).read_text())
    sql = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "FORWARD_SQL" for t in n.targets)
    )
    return re.search(
        r"CREATE FUNCTION operations\." + name + r"\(.*?\$fn\$;", sql, re.S
    )[0]


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1")
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as conn:
            conn.execute("""
                CREATE SCHEMA operations;
                CREATE TABLE operations.devices (tenant_id bigint, id uuid PRIMARY KEY);
                CREATE TABLE operations.computer_client_ownership (
                    tenant_id bigint, device_id uuid, state text, effective_client_id uuid,
                    evidence_revision bigint DEFAULT 0, contradiction boolean, reason text,
                    updated_at timestamptz, PRIMARY KEY (tenant_id, device_id));
                CREATE TABLE operations.source_record_subjects (
                    tenant_id bigint, id uuid PRIMARY KEY, subject_kind text,
                    input_version bigint DEFAULT 0, updated_at timestamptz,
                    source_instance_id uuid, observation_id uuid);
                CREATE TABLE operations.entity_observation_current (
                    tenant_id bigint, observation_id uuid, device_id uuid);
                CREATE TABLE operations.source_record_lookup_keys (
                    tenant_id bigint, subject_id uuid, source_instance_id uuid,
                    key_family text, normalized_value text);
                CREATE TABLE operations.source_record_assessment_queue (
                    tenant_id bigint, target_kind text, target_id uuid, target_key jsonb,
                    dirty_revision bigint DEFAULT 1, status text DEFAULT 'pending',
                    queued_at timestamptz DEFAULT now(),
                    PRIMARY KEY (tenant_id, target_kind, target_id));
            """)
            for name in (
                "tenant_guard_key",
                "tenant_guard_mode",
                "acquire_tenant_guard",
            ):
                conn.execute(function("0363_common_findings_expansion.py", name))
            for name in (
                "source_record_enqueue",
                "source_record_case_key_id",
                "source_record_enqueue_neighbors",
            ):
                conn.execute(function("0370_source_record_subjects.py", name))
            for name in (
                "lock_computer_client_scope",
                "lock_computer_client_scopes",
                "queue_source_client_reassessment",
                "queue_computer_client_reassessment",
                "invalidate_computer_client_ownership",
            ):
                conn.execute(function("0401_computer_client_ownership_state.py", name))
            for device in (A, B):
                conn.execute("INSERT INTO operations.devices VALUES (1, %s)", (device,))
                conn.execute(
                    "INSERT INTO operations.source_record_subjects (tenant_id,id,subject_kind,observation_id) VALUES (1,%s,'record',%s)",
                    (device, device),
                )
                conn.execute(
                    "INSERT INTO operations.entity_observation_current VALUES (1,%s,%s)",
                    (device, device),
                )
        yield dsn


@pytest.mark.parametrize("peer", ["ownership", "software_queue"])
@pytest.mark.parametrize("coordinated", [False, True])
def test_production_lock_paths(database, peer, coordinated):
    with psycopg.connect(database) as conn:
        conn.execute(
            "TRUNCATE operations.source_record_assessment_queue, operations.computer_client_ownership"
        )
        for device in (A, B):
            conn.execute(
                "INSERT INTO operations.computer_client_ownership (tenant_id,device_id,state,effective_client_id) VALUES (1,%s,'resolved',%s)",
                (device, CLIENT),
            )
    barrier = Barrier(2, timeout=8)
    source_started, peer_started = Event(), Event()

    def transaction(source):
        try:
            with psycopg.connect(database) as conn, conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '10s'")
                cur.execute("SET LOCAL deadlock_timeout = '100ms'")
                cur.execute("SET LOCAL operations.tenant_id = 1")
                if coordinated:
                    if not source:
                        assert source_started.wait(8)
                        peer_started.set()
                    guard_findings_writes(cur, 1)
                if source:
                    cur.execute(
                        "SELECT operations.invalidate_computer_client_ownership(1,%s)",
                        (B,),
                    )
                    if coordinated:
                        source_started.set()
                        assert peer_started.wait(8)
                    else:
                        barrier.wait()
                    cur.execute(
                        "SELECT operations.invalidate_computer_client_ownership(1,%s)",
                        (A,),
                    )
                else:
                    if peer == "ownership":
                        cur.execute(
                            "SELECT operations.lock_computer_client_scope(1,%s,%s)",
                            (A, CLIENT),
                        )
                    else:
                        cur.execute(
                            "SELECT operations.source_record_enqueue(1,'source_record',%s)",
                            (A,),
                        )
                    if not coordinated:
                        barrier.wait()
                    if peer == "ownership":
                        cur.execute(
                            "SELECT * FROM operations.lock_computer_client_scopes(1,%s::uuid[],%s::uuid[])",
                            ([A, B], [CLIENT, CLIENT]),
                        )
                    else:
                        cur.execute(
                            "SELECT operations.source_record_enqueue(1,'source_record',%s)",
                            (B,),
                        )
            return "committed"
        except psycopg.errors.DeadlockDetected:
            return "deadlock"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(transaction, source) for source in (True, False)]
        results = sorted(f.result(timeout=15) for f in futures)
    assert results == (
        ["committed", "committed"] if coordinated else ["committed", "deadlock"]
    )
    if coordinated:
        with psycopg.connect(database) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM operations.source_record_assessment_queue"
                ).fetchone()[0]
                == 2
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM operations.computer_client_ownership WHERE state='dirty'"
                ).fetchone()[0]
                == 2
            )


def test_guard_is_per_tenant_and_rollback_preserves_work(database):
    with psycopg.connect(database) as conn:
        before = conn.execute(
            "SELECT evidence_revision FROM operations.computer_client_ownership WHERE device_id=%s",
            (A,),
        ).fetchone()
        queued_before = conn.execute(
            "SELECT target_id,dirty_revision FROM operations.source_record_assessment_queue ORDER BY target_id"
        ).fetchall()
    with psycopg.connect(database) as source, psycopg.connect(database) as other:
        with source.cursor() as cur:
            guard_findings_writes(cur, 1)
            cur.execute(
                "SELECT operations.invalidate_computer_client_ownership(1,%s)", (A,)
            )
        with other.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '500ms'")
            guard_findings_writes(cur, 2)
        other.rollback()
        source.rollback()
        with other.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '500ms'")
            guard_findings_writes(cur, 1)
            cur.execute(
                "SELECT evidence_revision FROM operations.computer_client_ownership WHERE device_id=%s",
                (A,),
            )
            assert cur.fetchone() == before
            cur.execute(
                "SELECT target_id,dirty_revision FROM operations.source_record_assessment_queue ORDER BY target_id"
            )
            assert cur.fetchall() == queued_before
