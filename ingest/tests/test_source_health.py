from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ingest.source_health import blockers_for_platform, collection_problems
from shared.conditions.contracts import Condition, Participant, Readiness, Signal
from shared.conditions.engine import assess
from shared.conditions.policy import load_profile


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self.rows


def _row(*, status="completed", success=None, client_id=None):
    return (
        str(uuid4()), "Ninja", "Ninja", client_id, "interval:60", status,
        datetime(2026, 10, 8, 10, tzinfo=UTC), "collector error", success,
    )


def test_failed_source_refresh_becomes_a_binding_scoped_problem():
    problem = collection_problems(
        _Cursor([_row(status="failed")]), 1, datetime(2026, 10, 8, 11, tzinfo=UTC)
    )[0]

    assert problem.condition_key == f"source_failure:binding:{problem.binding_id}"
    assert problem.reason == "The latest collection attempt did not finish."


def test_only_overdue_successful_sources_become_problems():
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    problems = collection_problems(
        _Cursor(
            [
                _row(success=now - timedelta(hours=3)),
                _row(success=now - timedelta(hours=8, minutes=1)),
                _row(success=None),
            ]
        ),
        1,
        now,
    )

    assert len(problems) == 1
    assert problems[0].reason == "This source has not provided current data on its expected schedule."


def test_collection_blocker_respects_client_scope():
    global_problem, client_problem = collection_problems(
        _Cursor([_row(status="failed"), _row(status="failed", client_id=7)]),
        1,
        datetime(2026, 10, 8, 11, tzinfo=UTC),
    )

    assert blockers_for_platform([global_problem, client_problem], "Ninja", 7) == (
        global_problem.condition_key,
        client_problem.condition_key,
    )
    assert blockers_for_platform([global_problem, client_problem], "Ninja", 8) == (
        global_problem.condition_key,
    )


def test_source_issue_blocks_only_the_dependent_coverage_condition():
    participant = Participant("device", str(uuid4()), "affected", 1)
    source_problem = collection_problems(
        _Cursor([_row(status="failed")]), 1, datetime(2026, 10, 8, 11, tzinfo=UTC)
    )[0]
    decision = assess(
        Condition(
            1, "entity", str(uuid4()), "missing_required_platform", "coverage-key", "open", (participant,)
        ),
        load_profile(),
        (
            Signal("identity", participant, Readiness.READY, "identity:ready"),
            Signal(
                "collection", participant, Readiness.BLOCKED, "collection:source_problem",
                (source_problem.condition_key,),
            ),
            Signal("offline", participant, Readiness.READY, "offline:ready"),
        ),
        datetime(2026, 10, 8, 11, tzinfo=UTC),
        participant,
    )

    assert decision.disposition == "blocked"
    assert decision.blockers == (source_problem.condition_key,)
