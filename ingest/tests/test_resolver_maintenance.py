"""The resolver's hourly maintenance is paced by the database and reported in the Job result."""

from __future__ import annotations

import re
from contextlib import contextmanager

import pytest

from ingest import main
from ingest.identity import resolver


class _Cursor:
    """Answers by statement; records every statement it was sent."""

    def __init__(self, *, has_cadence=True, claimed=True):
        self.has_cadence = has_cadence
        self.claimed = claimed
        self.statements: list[str] = []
        self._row = None
        self._rows: list = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        self._rows = []
        if "to_regprocedure('operations.claim_maintenance" in sql:
            self._row = (self.has_cadence,)
        elif "to_regprocedure" in sql:
            self._row = (True,)
        elif "claim_maintenance(%s" in sql:
            self._row = (self.claimed,)
        elif "refresh_identity_roaming_records(%s)" in sql:
            self._row = (7,)
        elif "computer_name_shadow" in sql:
            self._rows = [
                (False, "rename", "current_label", 7),
                (True, "same", "withdrawn_os", 48),
            ]
        else:
            self._row = None

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def ran(self, fragment):
        return any(fragment in sql for sql in self.statements)


@pytest.fixture(autouse=True)
def _clean():
    resolver.reset_telemetry()
    yield
    resolver.reset_telemetry()


def test_roaming_runs_when_the_slot_is_free_and_records_its_completion():
    cur = _Cursor(claimed=True)
    resolver.refresh_roaming_records(cur)
    assert cur.ran("refresh_identity_roaming_records(%s)")
    assert cur.ran("complete_maintenance")
    telemetry = resolver.take_telemetry()
    assert telemetry["roaming"]["ran"] is True and telemetry["roaming"]["records"] == 7


def test_roaming_skips_when_another_run_had_the_slot_this_hour():
    cur = _Cursor(claimed=False)
    resolver.refresh_roaming_records(cur)
    assert not cur.ran("refresh_identity_roaming_records(%s)")
    assert resolver.take_telemetry() == {"roaming": {"ran": False}}


def test_roaming_still_runs_before_the_cadence_migration_exists():
    cur = _Cursor(has_cadence=False)
    resolver.refresh_roaming_records(cur)
    assert cur.ran("refresh_identity_roaming_records(%s)")
    assert not cur.ran("complete_maintenance")


def test_every_run_asks_the_database_not_process_memory():
    # Two runs in one process: each asks for the slot again.
    first, second = _Cursor(claimed=True), _Cursor(claimed=False)
    resolver.refresh_roaming_records(first)
    resolver.reset_telemetry()
    resolver.refresh_roaming_records(second)
    assert first.ran("claim_maintenance(%s") and second.ran("claim_maintenance(%s")


def test_shadow_naming_reports_aggregate_counts(monkeypatch):
    cursors = []

    @contextmanager
    def transaction():
        cur = _Cursor(claimed=True)
        cursors.append(cur)
        yield cur

    monkeypatch.setattr(resolver.db, "transaction", transaction)
    resolver.run_shadow_naming()
    shadow = resolver.take_telemetry()["shadow_naming"]
    assert shadow["ran"] is True
    assert shadow["counts"] == {
        "live:rename:current_label": 7,
        "retired:same:withdrawn_os": 48,
    }
    # Claim, read-only pass, completion: three transactions; the pass is read only.
    assert len(cursors) == 3
    assert cursors[1].statements[0] == "SET TRANSACTION READ ONLY"
    assert cursors[2].ran("complete_maintenance")


def test_the_resolver_job_returns_its_telemetry(monkeypatch):
    monkeypatch.setattr(main, "_drain_client_resolution", lambda: 0)

    def drain(**kwargs):
        resolver._add_count("observations_resolved", 3)
        resolver._telemetry["roaming"] = {"ran": False}
        return 3

    monkeypatch.setattr(main, "_drain_resolution", drain)
    result = main.run_identity_resolver_once()
    assert result.result["observations_resolved"] == 3
    assert result.result["roaming"] == {"ran": False}
    assert "seconds" in result.result
    # jobs_finish_v1 refuses result keys that look like credentials.
    assert not [
        k
        for k in result.result
        if re.search("token|secret|password|authorization|credential", k, re.I)
    ]
