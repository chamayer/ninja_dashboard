"""Every Jobs resource key the registry declares must have a capacity policy.

A key without a ``job_resource_limits`` row makes the dispatcher raise
"Jobs resource policy is unavailable", which stops the jobs worker.
"""

from pathlib import Path

from shared.jobs_registry import _CAPACITY_KEYS_BY_DEFINITION, _RESOURCE_KEYS_BY_DEFINITION

MIGRATIONS = sorted(Path("apps/core/migrations").glob("0*.py"))


def _declared_keys() -> set[str]:
    keys = set()
    for mapping in (_RESOURCE_KEYS_BY_DEFINITION, _CAPACITY_KEYS_BY_DEFINITION):
        for values in mapping.values():
            keys.update(values)
    return keys


def test_latest_limit_constraint_allows_every_declared_key():
    latest = [
        path.read_text(encoding="utf-8")
        for path in MIGRATIONS
        if "job_resource_limits_resource_template_check CHECK" in path.read_text(encoding="utf-8")
    ][-1]
    missing = sorted(key for key in _declared_keys() if f"'{key}'" not in latest)
    assert missing == []


def test_every_declared_key_has_a_limit_row():
    inserting = "\n".join(
        text
        for text in (path.read_text(encoding="utf-8") for path in MIGRATIONS)
        if "INSERT INTO operations.job_resource_limits" in text
    )
    missing = sorted(key for key in _declared_keys() if f"'{key}'" not in inserting)
    assert missing == []
