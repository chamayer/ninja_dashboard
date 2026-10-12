from ingest.agent_compliance.config_loader import (
    DEFAULT_MAX_AGE_DAYS,
    get_requirement,
)


def test_missing_requirement_uses_the_180_day_default():
    requirement = get_requirement([], client_id=1, device_scope="server")

    assert DEFAULT_MAX_AGE_DAYS == 180
    assert requirement.max_age_days == 180
