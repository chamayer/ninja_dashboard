"""Workflow admission must respect the scope rule the database enforces.

`operations.jobs_add_revision_dependency_v1` (migration 0272) requires:

* ``inherit``: the dependent's scope equals its PREREQUISITE run's scope;
* ``tenant``: the dependent's scope is ``tenant:1``.

`_admit_workflow` once sent the ROOT run's scope for every ``inherit`` edge.
Below a tenant-scoped edge (source-refresh -> resolver -> platform-evaluate) the
prerequisite is ``tenant:1`` while the root is bound to one source, so the
database raised "Jobs revision dependency context is invalid" and the whole
source refresh failed after its work was done. This replays every registry
workflow against a fake that applies the same two rules.
"""

from __future__ import annotations

import uuid

import pytest

from ingest import operator_job_queue
from shared.jobs_registry import definition, definitions

TENANT_SCOPE = "tenant:1"
SOURCE_SCOPE = "source-binding:00000000-0000-4000-8000-000000000013"


class _RuleEnforcingCursor:
    """Fake cursor that records created runs and applies the database's scope rule."""

    def __init__(self, root_id: uuid.UUID, root_key: str, root_scope: str) -> None:
        self.runs: dict[uuid.UUID, tuple[str, str]] = {root_id: (root_key, root_scope)}
        self.created: list[tuple[str, str]] = []
        self._next: uuid.UUID | None = None

    def execute(self, query: str, params: tuple = ()) -> None:
        if "jobs_request" in query:
            run_id = uuid.uuid4()
            key, scope = params[1], params[3]
            self.runs[run_id] = (key, scope)
            self.created.append((key, scope))
            self._next = run_id
        elif "jobs_add_revision_dependency_v1" in query:
            _tenant, dependent_id, prerequisite_id, revision, scope, _required = params
            prerequisite_key, prerequisite_scope = self.runs[prerequisite_id]
            dependent_key, dependent_scope = self.runs[dependent_id]
            contract = next(
                s
                for s in definition(prerequisite_key).successors
                if s.successor == dependent_key and s.revision_name == revision
            )
            invalid = dependent_scope != scope or (
                (contract.scope_mode == "inherit" and prerequisite_scope != scope)
                or (contract.scope_mode == "tenant" and scope != TENANT_SCOPE)
            )
            if invalid:
                raise RuntimeError("Jobs revision dependency context is invalid")
        else:  # pragma: no cover - the admission code issues only the two calls above
            raise AssertionError(f"unexpected SQL: {query[:60]}")

    def fetchone(self) -> tuple[uuid.UUID]:
        assert self._next is not None
        return (self._next,)


def _workflows() -> list[tuple[str, str, str]]:
    """Every (root job, condition, real root scope) a result can admit."""
    cases = []
    for job in definitions():
        scope = SOURCE_SCOPE if job.key == "source-refresh" else TENANT_SCOPE
        for condition in sorted({s.condition for s in job.successors} - {"always"}):
            cases.append((job.key, condition, scope))
    return cases


@pytest.mark.parametrize(("root_key", "condition", "root_scope"), _workflows())
def test_every_registry_workflow_satisfies_the_database_scope_rule(
    root_key, condition, root_scope
):
    root_id = uuid.uuid4()
    cur = _RuleEnforcingCursor(root_id, root_key, root_scope)
    operator_job_queue._admit_workflow(
        cur, root_key, root_id, root_scope, frozenset({condition})
    )


def test_identity_source_refresh_reaches_platform_evaluate_at_tenant_scope():
    """The case that failed in production: ScreenConnect's refresh after 609 s."""
    root_id = uuid.uuid4()
    cur = _RuleEnforcingCursor(root_id, "source-refresh", SOURCE_SCOPE)
    operator_job_queue._admit_workflow(
        cur, "source-refresh", root_id, SOURCE_SCOPE, frozenset({"identity_source"})
    )
    assert cur.created == [
        ("resolver", TENANT_SCOPE),
        ("platform-evaluate", TENANT_SCOPE),
    ]


def test_ninja_enrichment_reaches_platform_evaluate_through_patch_classify():
    root_id = uuid.uuid4()
    cur = _RuleEnforcingCursor(root_id, "ninja-enrichment", TENANT_SCOPE)
    operator_job_queue._admit_workflow(
        cur,
        "ninja-enrichment",
        root_id,
        TENANT_SCOPE,
        frozenset({"always"}),
    )
    assert dict(cur.created) == {
        "patches": TENANT_SCOPE,
        "patch-classify": TENANT_SCOPE,
        "platform-evaluate": TENANT_SCOPE,
    }


def test_a_tenant_scoped_root_keeps_its_scope_through_inherit_edges():
    root_id = uuid.uuid4()
    cur = _RuleEnforcingCursor(root_id, "agent-observations", TENANT_SCOPE)
    operator_job_queue._admit_workflow(cur, "agent-observations", root_id, TENANT_SCOPE)
    assert {scope for _key, scope in cur.created} == {TENANT_SCOPE}
