from ingest.evaluator import _apply_requirement_overrides


def _row(agent_id: int, platform: str) -> tuple:
    return (None, None, agent_id, "agent.security", platform, "all", None, "high", 24, 48, 168)


def _override(agent_id: int, platform: str, enabled: bool) -> tuple:
    return (*_row(agent_id, platform), enabled)


def test_enabled_client_override_adds_a_service_to_the_profile_baseline():
    effective = _apply_requirement_overrides(
        [_row(1, "Ninja")], [_override(2, "SentinelOne", True)]
    )

    assert {(row[2], row[4]) for row in effective} == {
        (1, "Ninja"),
        (2, "SentinelOne"),
    }


def test_disabled_client_override_removes_an_inherited_service():
    effective = _apply_requirement_overrides(
        [_row(1, "Ninja"), _row(2, "SentinelOne")],
        [_override(2, "SentinelOne", False)],
    )

    assert {(row[2], row[4]) for row in effective} == {(1, "Ninja")}


def test_enabled_client_override_replaces_profile_thresholds():
    baseline = _row(1, "Ninja")
    override = (*baseline[:7], "critical", 12, 24, 72, True)

    effective = _apply_requirement_overrides([baseline], [override])

    assert effective == [override[:11]]
