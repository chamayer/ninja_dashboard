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
