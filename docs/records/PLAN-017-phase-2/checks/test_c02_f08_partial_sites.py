"""Check 2 — F08: a failed SentinelOne sites fetch withdraws an empty site."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from conftest import observation_row
from ingest.connectors import sentinelone
from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SCOPE = "s1"
AGENT = {"id": 7, "computerName": "pc-7", "siteId": 100, "siteName": "Busy"}
SITES = [{"id": 100, "name": "Busy"}, {"id": 200, "name": "Empty"}]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, sites_fail: bool):
        self.sites_fail = sites_fail

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None, params=None):
        if url.endswith("/agents"):
            return _Response({"data": [AGENT], "pagination": {}})
        if self.sites_fail:
            raise RuntimeError("HTTP 503 from /sites")
        return _Response({"data": {"sites": SITES}, "pagination": {}})


def _fetch(monkeypatch, sites_fail: bool):
    monkeypatch.setattr(sentinelone.httpx, "Client", _FakeClient(sites_fail))
    source = SimpleNamespace(
        base_url="https://s1.invalid/web/api/v2.1",
        api_token="t",
        source_id=1,
        source_name="S1",
    )
    return sentinelone.fetch(source, T0)


def test_reproduces_sites_failure_is_swallowed_without_partial_signal(monkeypatch):
    rows = _fetch(monkeypatch, sites_fail=True)
    assert [r.get("platform_device_id") for r in rows] == ["7"]
    assert not any(r.get("_org_only") for r in rows)
    # Nothing in the returned rows can mark the snapshot partial; the writer
    # derives completeness from getattr(source, "is_partial_snapshot", False).
    assert all("is_partial_snapshot" not in r for r in rows)

    ok_rows = _fetch(monkeypatch, sites_fail=False)
    assert {r["platform_group_id"] for r in ok_rows if r.get("_org_only")} == {
        "100",
        "200",
    }


def _site(binding, instance, run_id, at, site_id):
    return observation_row(
        binding,
        instance,
        run_id,
        at,
        external_id=site_id,
        namespace="site",
        scope=SCOPE,
        entity_type="org",
    )


def _agent(binding, instance, run_id, at):
    return observation_row(
        binding, instance, run_id, at, external_id="7", namespace="agent", scope=SCOPE
    )


def _complete(cur, binding, at, rows_for_run):
    run_id, instance = begin_run(cur, 1, binding, SCOPE, at, expected_rows=0)
    rows = rows_for_run(run_id)
    write_current_rows(cur, rows)
    # write_observations passes is_complete_snapshot=True for SentinelOne.
    complete_run(cur, run_id, len(rows), is_complete_snapshot=True, identity_rows=rows)
    return run_id, reconcile_complete_run(cur, run_id)


def test_reproduces_false_withdrawal_and_closed_interval_after_retry(obs_conn):
    binding, instance = uuid.uuid4(), uuid.uuid4()
    t1, t2 = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
    with obs_conn.transaction(), obs_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO operations.source_bindings VALUES (%s, 1, %s)",
            (binding, instance),
        )
        # Healthy run: agent, its derived Busy site, and the empty site 200.
        _complete(cur, binding, T0, lambda r: [
            _agent(binding, instance, r, T0),
            _site(binding, instance, r, T0, "100"),
            _site(binding, instance, r, T0, "200"),
        ])
        # Sites endpoint fails: only agent-derived rows reach the writer.
        partial_run, withdrawn = _complete(cur, binding, t1, lambda r: [
            _agent(binding, instance, r, t1),
            _site(binding, instance, r, t1, "100"),
        ])
        assert withdrawn == 1
        cur.execute(
            "SELECT status, is_complete_snapshot FROM operations.observation_snapshot_runs"
            " WHERE run_id = %s",
            (partial_run,),
        )
        assert cur.fetchone() == ("complete", True)
        # Retry succeeds and sees the empty site again.
        _complete(cur, binding, t2, lambda r: [
            _agent(binding, instance, r, t2),
            _site(binding, instance, r, t2, "100"),
            _site(binding, instance, r, t2, "200"),
        ])
        cur.execute(
            """
            SELECT effective_from, effective_to, closed_by_snapshot_run_id
              FROM operations.entity_observation_history
             WHERE external_namespace = 'site' AND external_id = '200'
             ORDER BY effective_from
            """
        )
        history = cur.fetchall()
        cur.execute(
            "SELECT active FROM operations.entity_observation_current"
            " WHERE external_namespace = 'site' AND external_id = '200'"
        )
        assert cur.fetchone() == (True,)

    # Current behavior: a false absence interval [T0, t1) closed by the
    # partial run, then a new episode from t2.
    assert history == [(T0, t1, partial_run), (t2, None, None)]
