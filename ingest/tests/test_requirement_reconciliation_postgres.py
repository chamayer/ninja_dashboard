"""Requirement recovery with real coverage SQL, verdict writer and policy engine.

Only disposable synthetic PostgreSQL data; never a configured service. Uses
the production assessment/participant migrations and ADR-0035 verdict writer.
Shared relationship/state projection is covered by its own migration tests.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from ingest import evaluator
from ingest.tests.test_evaluator_lifecycle_postgres import _prepare_track_a_schema
from ingest.tests.test_evaluator_os_unknown_coverage_postgres import CLIENT, EXTRA
from ingest.tests.test_evaluator_requirement_state_postgres import HUDU, _computer

NOW = datetime.now(UTC)


def _sql(name):
    return importlib.import_module(f"operations.apps.core.migrations.{name}").FORWARD_SQL


@pytest.fixture(scope="module")
def database():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as conn:
            _prepare_track_a_schema(conn)
            conn.execute(EXTRA)
            conn.execute(HUDU)
            conn.execute("""
                CREATE ROLE operations_migrate SUPERUSER BYPASSRLS;
                CREATE ROLE operations_readonly;
                CREATE ROLE metabase_ro;
                CREATE TABLE operations.tenants (id bigint PRIMARY KEY);
                INSERT INTO operations.tenants VALUES (1), (2);
                ALTER TABLE operations.findings ADD COLUMN snoozed_until timestamptz;
                CREATE TABLE operations.change_history_registry (
                    table_name text PRIMARY KEY, classification text, reason text,
                    recorded_columns text[], secret_columns text[], key_columns text[],
                    computer_column text, computer_condition_column text,
                    computer_condition_value text, client_column text, is_global boolean,
                    capture text, enforce_action boolean DEFAULT false
                );
            """)
            for migration in (
                "0161_live_condition_contract", "0163_condition_assessment_policy_digest",
                "0166_condition_assessment_integrity", "0332_device_requirement_state",
            ):
                conn.execute(_sql(migration))
            # 0333's verdict constraint, without unrelated finding-type edits.
            conn.execute("""
                ALTER TABLE operations.device_requirement_state
                    DROP CONSTRAINT device_requirement_state_verdict_check;
                ALTER TABLE operations.device_requirement_state
                    ADD CONSTRAINT device_requirement_state_verdict_check CHECK (verdict IN (
                        'satisfied','missing','stale','exempt','outside_coverage',
                        'os_unknown','pending_cleanup'));
            """)
            policy = json.loads(
                (Path(__file__).parents[2]
                 / "shared/conditions/profile.json").read_text()
            )
            policy = importlib.import_module(
                "operations.apps.core.migrations.0296_slim_condition_policy"
            ).build_policy(policy)
            policy = importlib.import_module(
                "operations.apps.core.migrations.0320_os_unknown_coverage"
            ).build_policy(policy)
            digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            conn.execute(
                "INSERT INTO operations.condition_policy_versions(version,digest,policy,active) "
                "VALUES (%s,%s,%s::jsonb,true)",
                (policy["version"], digest, json.dumps(policy)),
            )
            conn.execute("""
                ALTER TABLE operations.finding_types ADD COLUMN covered_by jsonb DEFAULT '[]';
                INSERT INTO operations.finding_types
                    (id,name,default_severity,finding_class,auto_resolvable,category_id)
                VALUES (93,'device_offline','medium','entity',true,1),
                       (94,'device_missing_from_source','high','entity',true,1),
                       (95,'archived_but_reporting','medium','entity',true,1);
                UPDATE operations.finding_types
                   SET covered_by='["device_offline","device_missing_from_source","os_unknown_coverage"]'
                 WHERE id IN (90,91);
                ALTER TABLE operations.devices ADD COLUMN entity_id uuid DEFAULT gen_random_uuid();
                CREATE TABLE operations.entities (
                    id uuid,tenant_id bigint,retired_at timestamptz,retired_reason text,
                    updated_at timestamptz,updated_reason text
                );
            """)
            for migration in ("0301_finding_state", "0302_finding_state_skip_unchanged",
                              "0304_finding_cover_is_live", "0356_requirement_episode_identity"):
                conn.execute(_sql(migration))
            conn.execute("""
                GRANT USAGE ON SCHEMA operations TO ninja_ingest;
                GRANT SELECT ON ALL TABLES IN SCHEMA operations TO ninja_ingest;
                GRANT INSERT, UPDATE ON operations.findings TO ninja_ingest;
                ALTER TABLE operations.findings ENABLE ROW LEVEL SECURITY;
                CREATE POLICY tenant ON operations.findings
                    USING (tenant_id = current_setting('operations.tenant_id')::bigint);
                UPDATE operations.requirement_profile_items SET gap_after_hours=24;
                GRANT UPDATE ON operations.devices,operations.entities,
                    operations.device_operator_decisions TO ninja_ingest;
                GRANT SELECT,INSERT ON operations.audit_log TO ninja_ingest;
                CREATE TABLE operations.evaluation_probe (value integer);
                INSERT INTO operations.evaluation_probe VALUES (0);
            """)
            yield conn


@pytest.fixture
def conn(database):
    evaluator._finding_type_cache.clear()
    with database.transaction():
        database.execute("SET LOCAL operations.tenant_id=1")
        yield database
        raise psycopg.Rollback()


def _run(conn, device=None, problems=()):
    with conn.cursor() as cur:
        return evaluator._evaluate_coverage(cur, 1, device, NOW, list(problems), set())


def _seed(conn, device, *, kind="stale_required_platform", platform="Ninja",
          entity="agent.rmm", status="open", tenant=1, key=None):
    fid = uuid.uuid4()
    key = key or evaluator._condition_key(tenant, CLIENT, device, kind, platform)
    conn.execute(
        """INSERT INTO operations.findings
        (id,version,tenant_id,finding_type_id,client_id,subject_type,subject_id,
         finding_details,condition_key,severity,confidence,status,
         first_seen_at,last_seen_at,last_detected_at)
        VALUES (%s,1,%s,(SELECT id FROM operations.finding_types WHERE name=%s),
                %s,'device',%s,%s::jsonb,%s,'high','confirmed',%s,%s,%s,%s)""",
        (fid, tenant, kind, CLIENT, device,
         json.dumps({"entity_type": entity, "platform": platform}), key, status, NOW, NOW, NOW),
    )
    return fid


def _status(conn, fid):
    return conn.execute("SELECT status FROM operations.findings WHERE id=%s", (fid,)).fetchone()[0]


def _device(conn, *, age=1, **kwargs):
    device = _computer(conn, presence=[("agent.rmm", "Ninja", timedelta(hours=age))], **kwargs)
    conn.execute(
        "UPDATE operations.device_agent_presence_current "
        "SET last_contact_at=%s,last_observed_at=%s WHERE device_id=%s AND entity_type='agent.rmm'",
        (NOW - timedelta(hours=age), NOW, device),
    )
    return device


def test_24_hour_stale_is_not_closed_by_a_48_hour_rule_and_repeat_is_stable(conn):
    device = _device(conn, age=30)
    _run(conn, device)
    with conn.cursor() as cur:
        evaluator._auto_resolve(cur, 1, device, NOW)
    first = conn.execute(
        "SELECT id,status FROM operations.findings WHERE subject_id=%s AND finding_type_id=91",
        (device,),
    ).fetchall()
    assert len(first) == 1 and first[0][1] == "open"
    _run(conn, device)
    assert conn.execute(
        "SELECT id,status FROM operations.findings WHERE subject_id=%s AND finding_type_id=91",
        (device,),
    ).fetchall() == first


@pytest.mark.parametrize("status", ["open", "acknowledged", "investigating"])
def test_satisfied_requirement_refreshes_assessment_and_closes_old_finding(conn, status):
    device = _device(conn)
    fid = _seed(conn, device, status=status)
    _run(conn, device)
    assert _status(conn, fid) == "resolved"
    assert conn.execute(
        "SELECT response->>'may_clear' FROM operations.condition_assessments WHERE finding_id=%s",
        (fid,),
    ).fetchone() == ("true",)


@pytest.mark.parametrize("reason", ["identity", "collection", "offline", "suppressed", "snoozed"])
def test_current_guards_and_handling_prevent_clearing(conn, monkeypatch, reason):
    device = _device(conn, age=24*10 if reason == "offline" else 1)
    # Keep the requirement satisfied even when all device contact is offline.
    conn.execute("UPDATE operations.requirement_profile_items SET gap_after_hours=24*20")
    fid = _seed(conn, device, status="suppressed" if reason == "suppressed" else "open")
    if reason == "identity":
        monkeypatch.setattr(evaluator, "_identity_blocked_devices", lambda *args: {device})
    if reason == "snoozed":
        conn.execute("UPDATE operations.findings SET snoozed_until=%s WHERE id=%s",
                     (NOW + timedelta(days=1), fid))
    problems = [SimpleNamespace(platform="Ninja", client_id=CLIENT, condition_key="test-root")] \
        if reason == "collection" else []
    _run(conn, device, problems)
    assert _status(conn, fid) == ("suppressed" if reason == "suppressed" else "open")
    assert conn.execute(
        "SELECT response->>'may_clear' FROM operations.condition_assessments WHERE finding_id=%s",
        (fid,),
    ).fetchone() == ("false",)


@pytest.mark.parametrize("change", ["profile_removed", "unsupported_os", "exempt", "retired", "no_agents"])
def test_no_longer_required_is_reconciled_without_rederiving_policy(conn, change):
    device = _device(conn)
    fid = _seed(conn, device)
    if change == "profile_removed":
        conn.execute("DELETE FROM operations.requirement_profile_items")
    elif change == "unsupported_os":
        conn.execute("UPDATE operations.devices SET os_group='Other' WHERE id=%s", (device,))
    elif change == "exempt":
        conn.execute("INSERT INTO operations.device_operator_decisions VALUES "
                     "(1,%s,'exemptions','{\"agent.rmm\":true}')", (device,))
    elif change == "retired":
        conn.execute("UPDATE operations.devices SET lifecycle_status='retired' WHERE id=%s", (device,))
    else:
        conn.execute("DELETE FROM operations.device_agent_presence_current WHERE device_id=%s", (device,))
        conn.execute("UPDATE operations.entity_observation_current SET active=false WHERE device_id=%s", (device,))
        conn.execute("UPDATE operations.v_device_source_record_lifecycle_current "
                     "SET source_record_current=false,counts_as_current_computer_evidence=false "
                     "WHERE device_id=%s", (device,))
    _run(conn, device)
    # Withdrawing the final record now creates a measured cleanup condition;
    # its old requirement episode is retained, not blanket-closed.
    assert _status(conn, fid) == ("open" if change == "no_agents" else "resolved")


@pytest.mark.parametrize("change", ["unknown_os", "pending_cleanup", "cleanup_without_agents"])
def test_non_applicable_findings_keep_their_episode_and_get_current_assessments(conn, change):
    device = _device(conn)
    fid = _seed(conn, device)
    if change == "unknown_os":
        conn.execute("UPDATE operations.devices SET os_group='Unknown' WHERE id=%s", (device,))
    else:
        conn.execute("UPDATE operations.devices SET lifecycle_status='pending_cleanup' WHERE id=%s", (device,))
        if change == "cleanup_without_agents":
            conn.execute("DELETE FROM operations.device_agent_presence_current WHERE device_id=%s", (device,))
    _run(conn, device)
    assert _status(conn, fid) == "open"
    assert conn.execute("SELECT count(*) FROM operations.condition_assessments WHERE finding_id=%s",
                        (fid,)).fetchone() == (1,)


def test_single_device_and_tenant_scopes_do_not_clear_other_findings(conn):
    device, other = _device(conn), _device(conn)
    selected = _seed(conn, device)
    untouched = _seed(conn, other)
    cross_tenant = _seed(conn, device, tenant=2)
    conn.execute("SET LOCAL ROLE ninja_ingest")
    _run(conn, device)
    conn.execute("RESET ROLE")
    assert _status(conn, selected) == "resolved"
    assert _status(conn, untouched) == _status(conn, cross_tenant) == "open"


def test_unknown_os_finding_clears_on_a_single_computer_recovery(conn):
    device = _device(conn)
    fid = _seed(conn, device, kind="os_unknown_coverage", platform="", entity="")
    _run(conn, device)
    assert _status(conn, fid) == "resolved"


def test_distinct_entity_and_superseded_client_keys_are_not_current_episodes(conn):
    device = _device(conn, age=30)
    wrong_entity = _seed(conn, device, entity="agent.edr", key="legacy-wrong-entity")
    old_client = _seed(conn, device, key="legacy-client-key")
    _run(conn, device)
    assert _status(conn, wrong_entity) == _status(conn, old_client) == "resolved"
    assert conn.execute(
        "SELECT count(*) FROM operations.findings WHERE subject_id=%s "
        "AND finding_type_id=91 AND status='open'", (device,),
    ).fetchone() == (1,)


@pytest.mark.parametrize("transition", ["missing_to_stale", "stale_to_missing"])
def test_opposite_failure_is_replaced_without_leaving_both_open(conn, transition):
    device = _device(conn, age=30)
    old_kind = "missing_required_platform" if transition == "missing_to_stale" else "stale_required_platform"
    fid = _seed(conn, device, kind=old_kind)
    if transition == "stale_to_missing":
        conn.execute("DELETE FROM operations.device_agent_presence_current WHERE device_id=%s", (device,))
        conn.execute("UPDATE operations.entity_observation_current SET active=false WHERE device_id=%s", (device,))
        conn.execute("UPDATE operations.v_device_source_record_lifecycle_current "
                     "SET source_record_current=false,counts_as_current_computer_evidence=false "
                     "WHERE device_id=%s", (device,))
        conn.execute("INSERT INTO operations.device_operator_decisions VALUES "
                     "(1,%s,'in_use_confirmed','true')", (device,))
    _run(conn, device)
    assert _status(conn, fid) == "resolved"
    new_id = 91 if transition == "missing_to_stale" else 90
    assert conn.execute(
        "SELECT count(*) FROM operations.findings WHERE subject_id=%s "
        "AND finding_type_id=%s AND status='open' AND finding_details->>'platform'='Ninja'",
        (device, new_id),
    ).fetchone() == (1,)


def test_blocked_recovery_clears_only_after_source_health_recovers(conn):
    device = _device(conn)
    fid = _seed(conn, device)
    root = SimpleNamespace(platform="Ninja", client_id=CLIENT, condition_key="failed-source")
    _run(conn, device, [root])
    assert _status(conn, fid) == "open"
    _run(conn, device)
    assert _status(conn, fid) == "resolved"


def test_wildcard_presence_and_source_guard_use_the_current_verdict(conn):
    device = _device(conn)
    conn.execute("UPDATE operations.requirement_profile_items SET platform='any' WHERE platform='Ninja'")
    fid = _seed(conn, device, platform="any")
    root = SimpleNamespace(platform="Ninja", client_id=CLIENT, condition_key="failed-source")
    _run(conn, device, [root])
    assert _status(conn, fid) == "open"
    assert conn.execute(
        "SELECT verdict FROM operations.device_requirement_state WHERE device_id=%s AND platform='any'",
        (device,),
    ).fetchone() == ("satisfied",)
    _run(conn, device)
    assert _status(conn, fid) == "resolved"


def test_full_pass_reconciles_every_computer(conn):
    first, second = _device(conn), _device(conn)
    findings = [_seed(conn, first), _seed(conn, second)]
    _run(conn)
    assert [_status(conn, fid) for fid in findings] == ["resolved", "resolved"]


def test_failed_reconciliation_rolls_back_findings_assessments_and_verdicts(conn, monkeypatch):
    device = _device(conn, age=30)
    old = _seed(conn, device, kind="missing_required_platform")
    real = evaluator.record_assessment

    def fail_on_old(cur, condition, *args, **kwargs):
        if condition.row_id == str(old):
            raise RuntimeError("synthetic failure during reconciliation")
        return real(cur, condition, *args, **kwargs)

    monkeypatch.setattr(evaluator, "record_assessment", fail_on_old)
    with pytest.raises(RuntimeError, match="synthetic failure"), conn.transaction():
        _run(conn, device)
    assert _status(conn, old) == "open"
    assert conn.execute("SELECT count(*) FROM operations.device_requirement_state").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM operations.condition_assessments").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM operations.findings WHERE subject_id=%s",
                        (device,)).fetchone() == (1,)


def _pipeline(conn, device, problems=()):
    """The actual scoped domain stages, with real state/cover triggers enabled."""
    with conn.cursor() as cur:
        results, _ = evaluator._load_lifecycle_results(cur, 1, NOW, device, list(problems))
        evaluator._apply_lifecycle_results(cur, 1, NOW, uuid.uuid4(), results)
        evaluator._evaluate_coverage(cur, 1, device, NOW, list(problems), set(), results)
        evaluator._evaluate_device_lifecycle(cur, 1, device, NOW, list(problems), results)
    return results[device]


def test_integrated_contactless_poll_does_not_hide_aged_contact_and_recovery_uncovers(conn):
    device = _device(conn, age=24*45)
    # The production failure: an additional current agent record has no
    # contact time. Polling it just now must not invent positive contact.
    from ingest.tests.test_evaluator_os_unknown_coverage_postgres import lifecycle_record
    lifecycle_record(conn, device, "agent.remote_access", "ScreenConnect", NOW)
    conn.execute("INSERT INTO operations.device_agent_presence_current VALUES "
                 "(1,%s,'agent.remote_access','ScreenConnect',NULL,%s,NULL,NULL)", (device, NOW))
    fid = _seed(conn, device)
    result = _pipeline(conn, device)
    assert result.target == "pending_cleanup" and result.offline_since is not None
    assert conn.execute("SELECT attention FROM operations.finding_state WHERE finding_id=%s",
                        (fid,)).fetchone() == ("covered",)
    assert conn.execute("SELECT count(*) FROM operations.device_requirement_state_disagreements(1) "
                        "WHERE device_id=%s", (device,)).fetchone() == (0,)
    _pipeline(conn, device)
    assert conn.execute("SELECT count(*) FROM operations.findings WHERE subject_id=%s "
                        "AND finding_type_id=93 AND status='open'", (device,)).fetchone() == (1,)
    conn.execute("UPDATE operations.device_agent_presence_current SET last_contact_at=%s "
                 "WHERE device_id=%s AND platform='Ninja'", (NOW, device))
    recovered = _pipeline(conn, device)
    assert recovered.target == "active"
    assert _status(conn, fid) == "resolved"
    assert conn.execute("SELECT count(*) FROM operations.findings WHERE subject_id=%s "
                        "AND finding_type_id=93 AND status='open'", (device,)).fetchone() == (0,)


@pytest.mark.parametrize("os_group", ["Windows", "Unknown"])
def test_integrated_explicit_use_restores_checks_without_liveness_or_os_bypass(conn, os_group):
    device = _computer(conn, os_group=os_group, hudu="active")
    conn.execute("UPDATE operations.devices SET lifecycle_status='pending_cleanup' WHERE id=%s", (device,))
    conn.execute("INSERT INTO operations.device_operator_decisions VALUES "
                 "(1,%s,'in_use_confirmed','true')", (device,))
    result = _pipeline(conn, device)
    assert result.target == "pending_cleanup" and result.reason == "confirmed_in_use"
    assert not result.offline and not result.excludes_requirements
    verdict = conn.execute("SELECT verdict FROM operations.device_requirement_state "
                            "WHERE device_id=%s AND platform='Ninja'", (device,)).fetchone()[0]
    assert verdict == ("missing" if os_group == "Windows" else "os_unknown")
    conn.execute("DELETE FROM operations.device_operator_decisions WHERE device_id=%s", (device,))
    result = _pipeline(conn, device)
    assert result.excludes_requirements
    assert conn.execute("SELECT count(*) FROM operations.findings WHERE subject_id=%s "
                        "AND finding_type_id=94 AND status='open'", (device,)).fetchone() == (1,)


def test_integrated_documentation_cleanup_does_not_become_offline(conn):
    device = _computer(conn, hudu="active")
    fid = _seed(conn, device)
    result = _pipeline(conn, device)
    assert result.reason == "documentation_only" and not result.offline
    assert conn.execute("SELECT attention FROM operations.finding_state WHERE finding_id=%s",
                        (fid,)).fetchone() == ("covered",)
    assert conn.execute("SELECT count(*) FROM operations.findings WHERE subject_id=%s "
                        "AND finding_type_id=93", (device,)).fetchone() == (0,)


def test_integrated_failed_collection_preserves_root_and_cannot_clear_or_retire(conn):
    device = _device(conn, age=24*45)
    _pipeline(conn, device)
    root = conn.execute("SELECT id FROM operations.findings WHERE subject_id=%s "
                        "AND finding_type_id=93 AND status='open'", (device,)).fetchone()[0]
    conn.execute("UPDATE operations.device_agent_presence_current SET last_contact_at=%s "
                 "WHERE device_id=%s", (NOW, device))
    problem = SimpleNamespace(platform="Ninja", client_id=CLIENT, condition_key="failed-binding")
    result = _pipeline(conn, device, [problem])
    assert not result.known and _status(conn, root) == "open"
    _pipeline(conn, device)
    assert _status(conn, root) == "resolved"


def test_exact_audit_does_not_match_another_entity_or_superseded_episode(conn):
    device = _device(conn, age=30)
    _run(conn, device)
    stale = conn.execute("SELECT id FROM operations.findings WHERE subject_id=%s "
                         "AND finding_type_id=91", (device,)).fetchone()[0]
    conn.execute("UPDATE operations.findings SET finding_details="
                 "jsonb_set(finding_details,'{entity_type}','\"agent.edr\"') WHERE id=%s", (stale,))
    rows = conn.execute("SELECT disagreement FROM operations.device_requirement_state_disagreements(1) "
                         "WHERE device_id=%s", (device,)).fetchall()
    assert {r[0] for r in rows} == {"finding_without_verdict", "stale_without_finding"}


def test_evaluator_serializes_before_snapshot_and_releases_lock_on_failure(database, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from psycopg_pool import ConnectionPool
    entered, release = Event(), Event()
    observations = []
    with ConnectionPool(database.info.dsn, min_size=0, max_size=2) as pool:
        monkeypatch.setattr(evaluator.db, "pool", pool)

        def first():
            with evaluator._evaluation_transaction(1) as cur:
                cur.execute("SELECT value FROM operations.evaluation_probe")
                observations.append(cur.fetchone()[0])
                entered.set()
                assert release.wait(5)
                cur.execute("SELECT value FROM operations.evaluation_probe")
                observations.append(cur.fetchone()[0])

        def second():
            with evaluator._evaluation_transaction(1) as cur:
                cur.execute("SELECT value FROM operations.evaluation_probe")
                observations.append(cur.fetchone()[0])
                raise RuntimeError("synthetic evaluator failure")

        with ThreadPoolExecutor(max_workers=2) as workers:
            earlier = workers.submit(first)
            assert entered.wait(5)
            later = workers.submit(second)
            database.execute("UPDATE operations.evaluation_probe SET value=1")
            release.set()
            earlier.result(timeout=5)
            with pytest.raises(RuntimeError, match="synthetic evaluator failure"):
                later.result(timeout=5)
        assert observations == [0, 0, 1]
        with evaluator._evaluation_transaction(1) as cur:
            cur.execute("SELECT current_setting('operations.tenant_id')")
            assert cur.fetchone() == ("1",)
    database.execute("UPDATE operations.evaluation_probe SET value=0")
