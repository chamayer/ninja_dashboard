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


_COLUMN_SQL = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'operations' AND table_name = 'clients'
       AND column_name = 'offline_after_days')
"""


def override_expression(cur: Any, alias: str = "c") -> str:
    """SQL for a client's own "offline after" days, or NULL before the column exists.

    The column is added by a Django migration that can land after ingest starts,
    so a query must not name it until it is there.
    """
    cur.execute(_COLUMN_SQL)
    return f"{alias}.offline_after_days" if cur.fetchone()[0] else "NULL::integer"


def client_overrides(cur: Any, tenant_id: int) -> dict[str, int]:
    """Clients that set their own "offline after" days (client id -> days)."""
    expression = override_expression(cur, "c")
    if expression.startswith("NULL"):
        return {}
    cur.execute(
        "SELECT c.id::text, c.offline_after_days FROM operations.clients c "
        "WHERE c.tenant_id = %s AND c.offline_after_days IS NOT NULL",
        (tenant_id,),
    )
    return {str(client_id): int(days) for client_id, days in cur.fetchall()}


def device_overrides(cur: Any, tenant_id: int) -> dict[str, int]:
    """Computers whose client sets its own "offline after" days (device id -> days)."""
    overrides = client_overrides(cur, tenant_id)
    if not overrides:
        return {}
    cur.execute(
        "SELECT d.id::text, d.client_id::text FROM operations.devices d "
        "WHERE d.tenant_id = %s AND d.deleted_at IS NULL AND d.client_id IS NOT NULL",
        (tenant_id,),
    )
    return {
        str(device_id): overrides[client_id]
        for device_id, client_id in cur.fetchall()
        if client_id in overrides
    }


def device_offline_days(cur: Any, tenant_id: int, device_id: Any) -> int:
    """The "offline after" days that apply to one computer."""
    offline, _retire = load(cur, tenant_id)
    if not client_overrides(cur, tenant_id):
        return offline
    cur.execute(
        "SELECT d.client_id::text FROM operations.devices d "
        "WHERE d.tenant_id = %s AND d.id = %s",
        (tenant_id, str(device_id)),
    )
    row = cur.fetchone()
    return client_overrides(cur, tenant_id).get(row[0] if row else "", offline)


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
