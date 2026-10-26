"""F08 candidates for a failed SentinelOne sites fetch, on the real run primitives.

Option A — the writer marks the whole run partial when the sites substream
failed (`complete_run(..., is_complete_snapshot=False)`).
Option B — sites and their org rows live in their own snapshot scope, completed
only when the sites fetch succeeded; agents keep their own complete scope.

Each test seeds the same healthy run (two agents, a busy site, an empty site),
then a run in which agent 8 is gone and the sites fetch failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from ingest.observation_runs import begin_run, complete_run, reconcile_complete_run
from ingest.observations import write_current_rows

from conftest import phase2

obs_conn = phase2.obs_conn
observation_row = phase2.observation_row

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)


def _run(cur, binding, scope, at, rows_for_run, complete):
    run_id, instance = begin_run(cur, 1, binding, scope, at, expected_rows=0)
    rows = rows_for_run(run_id)
    write_current_rows(cur, rows)
    complete_run(cur, run_id, len(rows), is_complete_snapshot=complete, identity_rows=rows)
    return reconcile_complete_run(cur, run_id)


def _row(binding, instance, run_id, at, ext, ns, scope):
    return observation_row(binding, instance, run_id, at, external_id=ext, namespace=ns,
                           scope=scope, entity_type="org" if ns == "site" else "agent.test")


def _active(cur):
    cur.execute(
        "SELECT external_namespace || ':' || external_id FROM"
        " operations.entity_observation_current WHERE active ORDER BY 1"
    )
    return [r[0] for r in cur.fetchall()]


def _seed(cur):
    binding, instance = uuid.uuid4(), uuid.uuid4()
    cur.execute("INSERT INTO operations.source_bindings VALUES (%s, 1, %s)", (binding, instance))
    return binding, instance


def test_option_a_whole_run_partial_keeps_site_but_misses_agent_removal(obs_conn):
    with obs_conn.transaction(), obs_conn.cursor() as cur:
        binding, instance = _seed(cur)

        def r(rid, at, items):
            return [_row(binding, instance, rid, at, e, ns, "s1") for ns, e in items]

        _run(cur, binding, "s1", T0, lambda rid: r(rid, T0, [
            ("agent", "7"), ("agent", "8"), ("site", "100"), ("site", "200")]), True)
        withdrawn = _run(cur, binding, "s1", T1, lambda rid: r(rid, T1, [
            ("agent", "7"), ("site", "100")]), complete=False)
        assert withdrawn == 0
        # The empty site survives, but so does agent 8, which really left.
        assert _active(cur) == ["agent:7", "agent:8", "site:100", "site:200"]


def test_option_b_separate_sites_scope_keeps_site_and_withdraws_agent(obs_conn):
    with obs_conn.transaction(), obs_conn.cursor() as cur:
        binding, instance = _seed(cur)

        def rows(rid, at, scope, items):
            return [_row(binding, instance, rid, at, e, ns, scope) for ns, e in items]

        _run(cur, binding, "s1", T0, lambda rid: rows(rid, T0, "s1", [
            ("agent", "7"), ("agent", "8")]), True)
        _run(cur, binding, "s1.sites", T0, lambda rid: rows(rid, T0, "s1.sites", [
            ("site", "100"), ("site", "200")]), True)
        # Failed sites fetch: agents complete; the sites scope run is partial
        # and carries only the agent-derived site.
        agents_withdrawn = _run(cur, binding, "s1", T1, lambda rid: rows(rid, T1, "s1", [
            ("agent", "7")]), True)
        sites_withdrawn = _run(cur, binding, "s1.sites", T1, lambda rid: rows(
            rid, T1, "s1.sites", [("site", "100")]), complete=False)
        assert (agents_withdrawn, sites_withdrawn) == (1, 0)
        assert _active(cur) == ["agent:7", "site:100", "site:200"]
