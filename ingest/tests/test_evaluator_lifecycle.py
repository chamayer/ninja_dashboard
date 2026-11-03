from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from ingest.evaluator import (
    _lifecycle_target,
    _reported_lifecycle_state,
    _select_lifecycle_evidence,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def test_lifecycle_write_requires_current_computer_ownership(monkeypatch):
    from ingest import evaluator

    class Cursor:
        def __init__(self):
            self.locked = []

        def execute(self, _sql, params):
            self.locked.append(params)

        def fetchone(self):
            return (self.locked[-1][1] == 2,)

    def result(device_id):
        return SimpleNamespace(
            listing=SimpleNamespace(device_id=device_id, client_id=10, in_use_confirmed=False,
                                    reporting=False, lifecycle_status="active"),
            known=True, target="retired", reason="retire", evidence=None,
        )

    changed = []
    monkeypatch.setattr(evaluator, "_transition_lifecycle", lambda cur, tenant, item, *args:
                        changed.append(item.device_id) or True)
    cur = Cursor()
    assert evaluator._apply_lifecycle_results(cur, 1, NOW, None, {2: result(2), 1: result(1)}) == 1
    assert [params[1] for params in cur.locked] == [1, 2]
    assert changed == [2]


def test_device_finding_writers_skip_an_unresolved_owner():
    from ingest import evaluator

    class Cursor:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params):
            self.statements.append(sql)

        def fetchone(self):
            return (False,)

    for writer in (evaluator._upsert_finding, evaluator._upsert_lifecycle_finding):
        cur = Cursor()
        assert writer(cur, 1, 2, 3, 4, "key", "low", "confirmed", NOW, {}) == 0
        assert len(cur.statements) == 1
        assert "lock_computer_client_scope" in cur.statements[0]


def test_requirement_replacement_keeps_unlocked_computers_out_of_scope():
    from ingest import evaluator

    class Cursor:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=None):
            self.statements.append((sql, params))

        def fetchall(self):
            return [(1,)]

        def fetchone(self):
            return (True,)

    cur = Cursor()
    verdicts = [{"device_id": "1"}, {"device_id": "2"}]
    locked = evaluator._write_requirement_state(cur, 7, [(1, 11, 5), (2, 22, 9)], verdicts)
    assert locked == {1}
    assert cur.statements[-1][1][1] == [1]
    assert "owner.evidence_revision = captured.revision" in cur.statements[0][0]


def _row(
    *,
    mode: str,
    observed_at: datetime = NOW,
    contact_at: datetime | None = None,
    power_state: str | None = None,
    has_power_state: bool = False,
    reported_online: bool | None = None,
    has_reported_online_state: bool = False,
    entity_type: str = "agent.rmm",
    platform: str = "Ninja",
) -> dict:
    return {
        "entity_type": entity_type,
        "platform": platform,
        "mode": mode,
        "last_contact_at": contact_at,
        "last_observed_at": observed_at,
        "last_power_state": power_state,
        "has_power_state": has_power_state,
        "reported_online": reported_online,
        "has_reported_online_state": has_reported_online_state,
    }


def test_reported_power_state_is_an_exact_allowlist_and_beats_legacy_projection():
    assert _reported_lifecycle_state("poweredOn", True, False, True) == (
        "active",
        False,
    )
    assert _reported_lifecycle_state("poweredOff", True, True, True) == (
        "offline_aging",
        False,
    )
    assert _reported_lifecycle_state("suspended", True, True, True) == (
        "offline_aging",
        False,
    )
    assert _reported_lifecycle_state("paused", True, False, True) == (None, True)


def test_reported_online_is_used_only_when_power_state_is_absent():
    assert _reported_lifecycle_state(None, False, True, True) == ("active", False)
    assert _reported_lifecycle_state(None, False, False, True) == (
        "offline_aging",
        False,
    )
    assert _reported_lifecycle_state(None, False, None, True) == (None, True)
    assert _reported_lifecycle_state(None, False, None, False) == (None, False)


def test_present_null_power_state_is_unknown_not_a_legacy_offline_projection():
    assert _reported_lifecycle_state(None, True, False, False) == (None, True)


def test_newer_reported_state_beats_older_agent_contact():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(
                mode="direct_contact",
                contact_at=NOW - timedelta(minutes=1),
            ),
            _row(
                mode="reported_state",
                power_state="poweredOff",
                has_power_state=True,
                entity_type="vm.guest",
                platform="Hypervisor",
            ),
        ]
    )

    assert conflict is False
    assert evidence == {
        "kind": "reported_state",
        "status": "offline_aging",
        "at": NOW,
        "entity_type": "vm.guest",
        "platform": "Hypervisor",
    }


def test_direct_contact_wins_an_exact_timestamp_tie():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(mode="direct_contact", contact_at=NOW),
            _row(
                mode="reported_state",
                power_state="poweredOff",
                has_power_state=True,
                entity_type="vm.guest",
                platform="Hypervisor",
            ),
        ]
    )

    assert conflict is False
    assert evidence == {
        "kind": "direct_contact",
        "status": "active",
        "at": NOW,
        "entity_type": "agent.rmm",
        "platform": "Ninja",
    }


def test_equally_recent_conflicting_reported_states_do_not_select_lifecycle():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(mode="reported_state", power_state="poweredOn", has_power_state=True),
            _row(mode="reported_state", power_state="poweredOff", has_power_state=True),
        ]
    )

    assert evidence is None
    assert conflict is True


def test_lifecycle_target_preserves_three_state_aging_rules():
    assert _lifecycle_target({"status": "active", "at": NOW}, NOW, 7, 30) == "active"
    assert (
        _lifecycle_target(
            {"status": "active", "at": NOW - timedelta(days=7, seconds=1)}, NOW, 7, 30
        )
        == "offline_aging"
    )
    assert (
        _lifecycle_target(
            {"status": "offline_aging", "at": NOW - timedelta(days=30, seconds=1)}, NOW, 7, 30
        )
        == "pending_cleanup"
    )
    assert (
        _lifecycle_target({"status": "offline_aging", "at": NOW}, NOW, 7, 30)
        == "offline_aging"
    )


def test_newer_direct_contact_beats_older_reported_state_in_combined_mode():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(
                mode="direct_then_reported_state",
                contact_at=NOW,
                observed_at=NOW - timedelta(minutes=1),
                power_state="poweredOff",
                has_power_state=True,
                entity_type="vm.host",
                platform="Hypervisor",
            )
        ]
    )

    assert conflict is False
    assert evidence is not None
    assert evidence["kind"] == "direct_contact"
    assert evidence["status"] == "active"


def test_network_and_monitor_online_offline_states_are_qualified_reported_evidence():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(
                mode="reported_state",
                reported_online=True,
                has_reported_online_state=True,
                entity_type="network.device",
                platform="NetworkMonitor",
            ),
            _row(
                mode="reported_state",
                observed_at=NOW - timedelta(seconds=1),
                reported_online=False,
                has_reported_online_state=True,
                entity_type="monitor.target",
                platform="Probe",
            ),
        ]
    )

    assert conflict is False
    assert evidence is not None
    assert evidence["status"] == "active"
    assert evidence["entity_type"] == "network.device"


def test_equally_recent_matching_reported_states_select_deterministically():
    evidence, conflict = _select_lifecycle_evidence(
        [
            _row(
                mode="reported_state",
                power_state="poweredOff",
                has_power_state=True,
                entity_type="vm.guest",
                platform="Hypervisor",
            ),
            _row(
                mode="reported_state",
                reported_online=False,
                has_reported_online_state=True,
                entity_type="monitor.target",
                platform="Probe",
            ),
        ]
    )

    assert conflict is False
    assert evidence is not None
    assert evidence["status"] == "offline_aging"
    assert evidence["entity_type"] == "vm.guest"


def test_no_qualified_evidence_keeps_lifecycle_unchanged():
    assert _select_lifecycle_evidence([_row(mode="none")]) == (None, False)


def test_lifecycle_target_keeps_exact_aging_boundaries_in_the_younger_bucket():
    assert (
        _lifecycle_target({"status": "active", "at": NOW - timedelta(days=7)}, NOW, 7, 30)
        == "active"
    )
    assert (
        _lifecycle_target({"status": "active", "at": NOW - timedelta(days=30)}, NOW, 7, 30)
        == "offline_aging"
    )
