"""Focused contract checks for the Jobs pool-dispatch migration."""

from pathlib import Path


def test_pool_dispatch_keeps_ready_bounded_and_domain_locks_fixed():
    sql = Path("apps/core/migrations/0255_jobs_dispatch_capacity_pools.py").read_text(
        encoding="utf-8"
    )

    assert "'capacity:external-io', 2" in sql
    assert "'capacity:processing', 1" in sql
    assert "'capacity:control', 1" in sql
    assert "'execution:emergency-child', 4" in sql
    assert "policy_kind IN ('execution_pool', 'domain_lock', 'legacy_compatibility')" in sql
    assert "WHILE v_ready < 2 LOOP" in sql
    assert "jobs_default_waiting_before_write" in sql
    assert "operations.jobs_ready_promotion" in sql
    assert "operations.jobs_claim_next_v6" in sql
    assert "execution:emergency-child" in sql
    assert "jobs_resource_policy_diagnostics_v1" in sql
    assert "jobs_set_execution_pool_capacity_v1" in sql


def test_queued_wait_stages_are_derived_from_the_wait_category():
    sql = Path("apps/core/migrations/0256_jobs_waiting_stage_truth.py").read_text(encoding="utf-8")

    assert "WHEN 'dependency' THEN 'Waiting for data'" in sql
    assert "WHEN 'resource' THEN 'Waiting for protected work'" in sql
    assert "WHEN 'capacity' THEN 'Waiting for capacity'" in sql
    assert "UPDATE operations.operator_job_runs" in sql


def test_ready_dispatch_skips_capacity_blocked_work_for_runnable_work():
    sql = Path("apps/core/migrations/0257_jobs_dispatch_runnable_ready.py").read_text(
        encoding="utf-8"
    )

    assert "NOT run.id = ANY(v_examined)" in sql
    assert "v_available := TRUE" in sql
    assert "state IN ('held', 'contained')" in sql
    assert "IF NOT v_available THEN" in sql
    assert "CONTINUE;" in sql


def test_every_definition_declares_recovery_posture():
    registry = Path("../shared/jobs_registry.py").read_text(encoding="utf-8")
    recovery = Path("apps/core/migrations/0258_jobs_recovery_contract.py").read_text(
        encoding="utf-8"
    )

    assert '"recovery_mode": _RECOVERY_MODE_BY_DEFINITION[self.key]' in registry
    assert '"manual_review"' in registry
    assert "agent-observations" in recovery
    assert "documentation-observations" in recovery
