"""Check 1 — F01: an empty generic collection skips absence reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import observation_row
from ingest import source_observations
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SCOPE = "Test"


def _seed_active_record(conn):
    """One prior complete run leaves one active record for the scope."""
    binding_id, instance_id = uuid.uuid4(), uuid.uuid4()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)",
            (binding_id, instance_id),
        )
        run_id, _ = begin_run(cur, 1, binding_id, SCOPE, T0, expected_rows=1)
        row = observation_row(binding_id, instance_id, run_id, T0, external_id="1")
        assert write_current_rows(cur, [row]) == 1
        complete_run(cur, run_id, 1, is_complete_snapshot=True, identity_rows=[row])
        reconcile_complete_run(cur, run_id)
    return binding_id, instance_id


def _state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT active, withdrawn_at FROM operations.entity_observation_current"
        )
        current = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM operations.observation_snapshot_runs")
        runs = cur.fetchone()[0]
    return current, runs


def _source(binding_id, instance_id, **extra):
    return SimpleNamespace(
        platform="Test",
        source_key=SCOPE,
        source_name=SCOPE,
        source_binding_id=binding_id,
        source_instance_id=instance_id,
        entity_type="agent.test",
        **extra,
    )


def _run_collection(monkeypatch, source, fetch):
    recorded = []
    monkeypatch.setitem(source_observations._FETCHERS, "Test", fetch)
    monkeypatch.setattr(
        source_observations,
        "_record_source_run",
        lambda _source, _started, ok, rows, error="": recorded.append((ok, rows)),
    )

    def no_db():
        raise AssertionError("writer opened a transaction")

    monkeypatch.setattr(source_observations.db, "transaction", no_db)
    return recorded


def test_reproduces_empty_complete_fetch_reported_ok_without_a_run(
    obs_conn, monkeypatch
):
    binding_id, instance_id = _seed_active_record(obs_conn)
    recorded = _run_collection(
        monkeypatch, _source(binding_id, instance_id), lambda _s, _t: []
    )

    counts = source_observations.run_source_observations(
        [_source(binding_id, instance_id)], T0 + timedelta(hours=1)
    )

    # Current behavior: healthy run-log receipt, no snapshot run, no withdrawal.
    assert counts == {"Test": 0}
    assert recorded == [(True, 0)]
    assert _state(obs_conn) == ([(True, None)], 1)


def test_counterfactual_shared_primitives_withdraw_on_complete_empty(obs_conn):
    binding_id, _ = _seed_active_record(obs_conn)
    absent_at = T0 + timedelta(hours=1)
    with obs_conn.transaction(), obs_conn.cursor() as cur:
        run_id, _ = begin_run(cur, 1, binding_id, SCOPE, absent_at, expected_rows=0)
        complete_run(cur, run_id, 0, is_complete_snapshot=True, identity_rows=[])
        assert reconcile_complete_run(cur, run_id) == 1
    assert _state(obs_conn) == ([(False, absent_at)], 2)


def test_control_partial_snapshot_does_not_authorize_absence(obs_conn):
    binding_id, _ = _seed_active_record(obs_conn)
    with obs_conn.transaction(), obs_conn.cursor() as cur:
        run_id, _ = begin_run(
            cur, 1, binding_id, SCOPE, T0 + timedelta(hours=1), expected_rows=0
        )
        complete_run(cur, run_id, 0, is_complete_snapshot=False, identity_rows=[])
        assert reconcile_complete_run(cur, run_id) == 0
    assert _state(obs_conn) == ([(True, None)], 2)


def test_control_fetch_failure_is_reported_and_leaves_evidence(
    obs_conn, monkeypatch
):
    binding_id, instance_id = _seed_active_record(obs_conn)

    def broken(_s, _t):
        raise RuntimeError("connector failed")

    recorded = _run_collection(monkeypatch, _source(binding_id, instance_id), broken)

    with pytest.raises(source_observations.SourceObservationFailure):
        source_observations.run_source_observations(
            [_source(binding_id, instance_id)], T0 + timedelta(hours=1)
        )
    assert recorded == [(False, 0)]
    assert _state(obs_conn) == ([(True, None)], 1)
