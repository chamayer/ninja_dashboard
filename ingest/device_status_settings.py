"""The tenant's "offline" and "review for retirement" thresholds, in one place.

Operations writes these on the Device status page (``evaluator_config`` row
``device_status``). Every ingest consumer that decides a computer is offline
reads them here: lifecycle aging, the ``device_offline`` finding, the
stale-agent demotion, and the offline gate for patch and software readiness.
``patch_activity_days`` is a different question (is patch data stale) and is
not read here.
"""

from __future__ import annotations

from typing import Any

# Fail-closed fallbacks for a tenant that never saved the setting.
DEFAULT_OFFLINE_AFTER_DAYS = 7
DEFAULT_RETIRE_REVIEW_DAYS = 30

_OFFLINE_KEY = "active_device_days"
_RETIRE_KEY = "retire_review_days"


def thresholds(stored: Any) -> tuple[int, int]:
    """Return (offline_after_days, retire_review_days) from a stored config."""
    stored = stored if isinstance(stored, dict) else {}

    def read(key: str, default: int) -> int:
        try:
            return max(1, int(stored.get(key, default)))
        except (TypeError, ValueError):
            return default

    offline = read(_OFFLINE_KEY, DEFAULT_OFFLINE_AFTER_DAYS)
    retire = read(_RETIRE_KEY, DEFAULT_RETIRE_REVIEW_DAYS)
    # A computer cannot be due for retirement review before it is offline.
    return offline, max(retire, offline + 1)


def load(cur: Any, tenant_id: int) -> tuple[int, int]:
    """Read the tenant's thresholds with a cursor."""
    cur.execute(
        """
        SELECT config FROM operations.evaluator_config
         WHERE tenant_id = %s AND evaluator_name = 'device_status'
        """,
        (tenant_id,),
    )
    row = cur.fetchone()
    return thresholds(row[0] if row else None)
