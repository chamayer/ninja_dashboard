from shared.jobs_registry import definition, schedule_definitions


def test_dirty_ownership_has_priority_and_source_successors():
    ownership = definition("computer-client-ownership")
    assert ownership.priority > definition("resolver").priority
    assert ownership.resource_keys == ()
    assert ownership.snapshot_metadata()["recovery_mode"] == "manual_review"

    source_successors = {
        edge.successor: edge for edge in definition("source-refresh").successors
    }
    assert source_successors["computer-client-ownership"].condition == "identity_source"

    resolver_successors = {
        edge.successor: edge for edge in definition("resolver").successors
    }
    assert resolver_successors["computer-client-ownership"].revision_name == "identity.current"


def test_full_sweep_is_daily_maintenance_without_holding_identity_job_lock():
    sweep = definition("computer-client-ownership-sweep")
    schedule = next(
        item for item in schedule_definitions()
        if item.schedule_id == "computer_client_ownership_sweep_cycle"
    )
    assert schedule.cadence_setting == "constant:24"
    assert sweep.priority < definition("resolver").priority
    assert sweep.resource_keys == ()
    assert sweep.snapshot_metadata()["recovery_mode"] == "manual_review"
