"""Candidate reuse saves queries without sharing version filters or stale runs."""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

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


def test_same_candidate_set_reuses_the_exact_rows():
    cur = MagicMock()
    cur.fetchall.return_value = [("cpe-one", "1"), ("cpe-all", "*")]
    cache = matcher._CpeCandidateCache()
    first = cache.lookup(cur, {("vendor-b", "p-b"), ("vendor-a", "p-a")}, set())
    second = cache.lookup(cur, {("vendor-a", "p-a"), ("vendor-b", "p-b")}, set())
    assert first == second == (("cpe-one", "1"), ("cpe-all", "*"))
    cur.execute.assert_called_once()
    assert cur.execute.call_args.args[1] == (["vendor-a", "vendor-b"], ["p-a", "p-b"])
    assert (cache.hits, cache.misses) == (1, 1)


def test_empty_results_are_reused_but_different_tiers_are_not():
    cur = MagicMock()
    cur.fetchall.return_value = []
    cache = matcher._CpeCandidateCache()
    assert cache.lookup(cur, set(), {"widget"}) == ()
    assert cache.lookup(cur, set(), {"widget"}) == ()
    assert cache.lookup(cur, {("vendor", "widget")}, set()) == ()
    assert cur.execute.call_count == 2


def test_row_budget_evicts_the_least_recently_used_pool():
    cur = MagicMock()
    cur.fetchall.return_value = [("cpe", "*")]
    cache = matcher._CpeCandidateCache(max_rows=2, max_entries=10)
    for product in ("a", "b", "a", "c", "a", "b"):
        cache.lookup(cur, set(), {product})
        assert cache.rows <= 2
    # 'a' stays hot; loading c evicts b, which must be loaded again at the end.
    assert (cache.hits, cache.misses, cache.evictions) == (2, 4, 2)


def test_oversized_pools_are_returned_in_full_without_retention():
    rows = [(f"cpe-{n}", str(n)) for n in range(4)]
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cache = matcher._CpeCandidateCache(max_rows=2)
    assert cache.lookup(cur, {("vendor", "large")}, set()) == tuple(rows)
    assert cache.lookup(cur, {("vendor", "large")}, set()) == tuple(rows)
    assert cache.rows == 0
    assert cur.execute.call_count == 2


def test_empty_pool_entries_are_bounded_too():
    cur = MagicMock()
    cur.fetchall.return_value = []
    cache = matcher._CpeCandidateCache(max_entries=2)
    for product in ("a", "b", "c", "a"):
        cache.lookup(cur, set(), {product})
    assert cache.rows == 0
    assert cache.evictions == 2
    assert cache.misses == 4


def test_failed_candidate_query_is_not_cached():
    cur = MagicMock()
    cur.execute.side_effect = [RuntimeError("database failure"), None]
    cur.fetchall.return_value = [("cpe", "1")]
    cache = matcher._CpeCandidateCache()
    with pytest.raises(RuntimeError, match="database failure"):
        cache.lookup(cur, set(), {"widget"})
    assert cache.lookup(cur, set(), {"widget"}) == (("cpe", "1"),)
    assert cur.execute.call_count == 2


def test_cve_batches_preserve_the_union_and_do_not_count_duplicates_twice():
    candidates = [f"cpe-{n}" for n in range(matcher._CVE_LOOKUP_BATCH_SIZE + 3)]
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("CVE-shared",), ("CVE-first",)],
        [("CVE-shared",), ("CVE-second",)],
    ]
    cache = {}
    result = matcher._cves_for(cur, candidates, cache)
    assert result == ["CVE-shared", "CVE-first", "CVE-second"]
    assert [len(call.args[1][0]) for call in cur.execute.call_args_list] == [500, 3]
    assert matcher._cves_for(cur, candidates, cache) == result
    assert cur.execute.call_count == 2


def test_a_failed_cve_batch_does_not_cache_a_partial_result():
    candidates = [f"cpe-{n}" for n in range(matcher._CVE_LOOKUP_BATCH_SIZE + 1)]
    cur = MagicMock()
    cur.execute.side_effect = [None, RuntimeError("database failure"), None, None]
    cur.fetchall.side_effect = [[("CVE-first",)], [("CVE-first",)], [("CVE-last",)]]
    cache = {}
    with pytest.raises(RuntimeError, match="database failure"):
        matcher._cves_for(cur, candidates, cache)
    assert tuple(candidates) not in cache
    assert matcher._cves_for(cur, candidates, cache) == ["CVE-first", "CVE-last"]


def test_batched_cve_lookup_equals_one_any_candidate_lookup():
    candidates = [f"cpe-{n}" for n in range(1507)]
    affected = {
        "CVE-a": {"cpe-0", "cpe-1001"},
        "CVE-b": {"cpe-1499"},
        "CVE-c": {"cpe-1506", "cpe-500"},
        "CVE-absent": {"outside"},
    }

    class Cursor:
        def execute(self, sql, params):
            selected = set(params[0])
            self.rows = [(cve,) for cve, cpes in affected.items() if cpes & selected]

        def fetchall(self):
            return self.rows

    expected = {cve for cve, cpes in affected.items() if cpes & set(candidates)}
    assert set(matcher._cves_for(Cursor(), candidates, {})) == expected


class _MatcherCursor:
    def __init__(self, fallback=False):
        self.titles = ("Widget Basic", "Widget Pro") if fallback else (
            "Acme Widget Basic", "Acme Widget Pro"
        )
        self.cpe_rows = [("cpe-all", "*"), ("cpe-v1", "1.0"), ("cpe-v2", "2.0")]
        self.cves = {"cpe-all": "CVE-all", "cpe-v1": "CVE-v1", "cpe-v2": "CVE-v2"}
        self.matches = []
        self.before = []
        self.desired = []
        self.candidate_queries = 0
        self.result = []
        self.deletes = 0

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        if sql.startswith("SELECT DISTINCT p.canonical_name"):
            self.result = [(self.titles[0], 101, "1.0"), (self.titles[1], 202, "2.0")]
        elif sql.startswith("SELECT DISTINCT LOWER(vendor)"):
            self.result = [("acme", "widget")]
        elif "SELECT c.cpe23, c.version" in sql or "SELECT cpe23, version" in sql:
            self.candidate_queries += 1
            self.result = list(self.cpe_rows)
        elif sql.startswith("SELECT cve_id"):
            self.result = [(self.cves[cpe],) for cpe in params[0] if cpe in self.cves]
        elif sql.startswith("CREATE TEMP TABLE cve_match_before"):
            self.before = list(self.matches)
        elif sql.startswith("CREATE TEMP TABLE cve_match_desired"):
            self.desired = []
        elif sql.startswith("CREATE UNIQUE INDEX cve_match_desired_scope_idx"):
            pass
        elif sql.startswith("DELETE FROM operations.cve_match"):
            self.deletes += 1
            desired_keys = {row[:5] for row in self.desired}
            self.matches = [row for row in self.matches if row[:5] in desired_keys]
        elif sql.startswith("INSERT INTO operations.cve_match AS existing"):
            self.matches = list(self.desired)
        elif sql.startswith("SELECT EXISTS"):
            self.result = [(set(self.before) != set(self.matches),)]
        elif sql.startswith("SELECT to_regclass"):
            self.result = [(False if "IS NOT NULL" in sql else None,)]
        else:
            raise AssertionError(f"Unexpected matcher statement: {sql}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0]

    def executemany(self, sql, rows):
        assert "INSERT INTO pg_temp.cve_match_desired" in sql
        self.desired.extend(rows)


def _use_cursor(monkeypatch, cursor):
    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr(matcher.db, "transaction", transaction)
    monkeypatch.setattr(matcher, "_load_hints", lambda: (set(), []))


@pytest.mark.parametrize("fallback", [False, True])
def test_full_match_keeps_each_versions_matches_and_reduces_queries(monkeypatch, fallback):
    cur = _MatcherCursor(fallback)
    _use_cursor(monkeypatch, cur)
    result = matcher._match_and_upsert()
    assert int(result) == 4
    assert cur.candidate_queries == 1
    expected = {
        (cur.titles[0], None, "CVE-all"), (cur.titles[0], 101, "CVE-v1"),
        (cur.titles[1], None, "CVE-all"), (cur.titles[1], 202, "CVE-v2"),
    }
    assert {(row[1], row[2], row[3]) for row in cur.matches} == expected
    cached_matches = set(cur.matches)

    real_cache = matcher._CpeCandidateCache
    monkeypatch.setattr(matcher, "_CpeCandidateCache", lambda: real_cache(max_entries=0))
    uncached = _MatcherCursor(fallback)
    _use_cursor(monkeypatch, uncached)
    assert int(matcher._match_and_upsert()) == 4
    assert uncached.candidate_queries == 2
    assert set(uncached.matches) == cached_matches


def test_next_full_run_reloads_candidates_and_withdraws_old_matches(monkeypatch):
    cur = _MatcherCursor()
    _use_cursor(monkeypatch, cur)
    assert int(matcher._match_and_upsert()) == 4
    cur.cpe_rows = []
    result = matcher._match_and_upsert()
    assert int(result) == 0
    assert result.material_changed is True
    assert cur.matches == []
    assert cur.candidate_queries == 2
    assert cur.deletes == 2


def test_identical_full_refresh_does_not_report_material_changes(monkeypatch):
    cur = _MatcherCursor()
    _use_cursor(monkeypatch, cur)
    assert matcher._match_and_upsert().material_changed is True
    before = set(cur.matches)
    result = matcher._match_and_upsert()
    assert int(result) == 4
    assert result.material_changed is False
    assert set(cur.matches) == before
    assert cur.candidate_queries == 2
