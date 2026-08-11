"""ADR-0015 step 6: the software classifier runs on a schedule.

Two things are enforced here, both of which would fail silently in
production rather than raise:

1. The scheduled path must not re-run the intel matcher / Winget /
   Chocolatey enrichers. Those are registered as their own scheduler jobs,
   so duplicating them here would double that work on every tick while
   still looking correct in the logs.
2. The catch-up predicate must read `operations.run_log`. The generic
   `should_catch_up()` helper reads `ninja_core.run_log` on a different
   column set, so pointing it at 'software_classifier' would match no row,
   return False, and disable the catch-up with no error anywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

main = pytest.importorskip("ingest.main")

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, row: tuple | None) -> None:
        self.row = row
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, params: tuple | None = None) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple | None:
        return self.row


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, row: tuple | None) -> None:
        self.cursor = _Cursor(row)

    def connection(self) -> _Connection:
        return _Connection(self.cursor)


class _FailingPool:
    def connection(self):
        raise RuntimeError("database unreachable")


def _stub_classifier(monkeypatch) -> list[str]:
    """Record which steps a classify run performs."""
    called: list[str] = []
    monkeypatch.setattr(main.settings, "INTEL_ENABLED", True)
    for name in ("run_intel_matcher_once", "run_intel_winget_once",
                 "run_intel_chocolatey_once"):
        monkeypatch.setattr(main, name, lambda n=name: called.append(n))
    monkeypatch.setattr(main, "software_classify", lambda tenant_id: called.append("classify") or 0)
    # The matview refresh talks to the database; it is not under test here.
    monkeypatch.setattr(main.db, "pool", _Pool(None))
    return called


def test_scheduled_run_skips_the_already_scheduled_intel_steps(monkeypatch) -> None:
    called = _stub_classifier(monkeypatch)

    main.run_software_classify_scheduled()

    assert called == ["classify"]


def test_manual_run_still_enriches_intel_first(monkeypatch) -> None:
    called = _stub_classifier(monkeypatch)

    main.run_software_classify_once()

    assert called == [
        "run_intel_matcher_once",
        "run_intel_winget_once",
        "run_intel_chocolatey_once",
        "classify",
    ]


def test_classifier_ordering_puts_intel_before_classify(monkeypatch) -> None:
    """The enrichers exist to make cve_match fresh *for* the classifier."""
    called = _stub_classifier(monkeypatch)

    main.run_software_classify_once()

    assert called.index("run_intel_matcher_once") < called.index("classify")


def test_overdue_when_the_classifier_has_never_run(monkeypatch) -> None:
    monkeypatch.setattr(main.db, "pool", _Pool(None))

    assert main.software_classify_overdue(24, now=_NOW) is True


def test_overdue_when_the_last_run_predates_the_schedule(monkeypatch) -> None:
    monkeypatch.setattr(main.db, "pool", _Pool((_NOW - timedelta(hours=25),)))

    assert main.software_classify_overdue(24, now=_NOW) is True


def test_not_overdue_after_a_recent_run(monkeypatch) -> None:
    monkeypatch.setattr(main.db, "pool", _Pool((_NOW - timedelta(hours=1),)))

    assert main.software_classify_overdue(24, now=_NOW) is False


def test_naive_timestamps_are_read_as_utc(monkeypatch) -> None:
    """`operations.run_log.ended_at` can come back without a tzinfo."""
    monkeypatch.setattr(
        main.db, "pool", _Pool((datetime(2026, 8, 11, 11, 0),))
    )

    assert main.software_classify_overdue(24, now=_NOW) is False


def test_a_probe_failure_assumes_overdue_rather_than_skipping(monkeypatch) -> None:
    """Failing closed the other way would skip the run and log nothing useful."""
    monkeypatch.setattr(main.db, "pool", _FailingPool())

    assert main.software_classify_overdue(24, now=_NOW) is True


def test_it_reads_the_operations_run_log_not_the_ninja_core_one(monkeypatch) -> None:
    pool = _Pool((_NOW,))
    monkeypatch.setattr(main.db, "pool", pool)

    main.software_classify_overdue(24, now=_NOW)

    statement = " ".join(pool.cursor.statements)
    assert "operations.run_log" in statement
    assert "ninja_core.run_log" not in statement
    assert "software_classifier" in statement
