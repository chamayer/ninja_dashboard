"""Tenant policy for device status and patching posture."""

from __future__ import annotations

from .models import EvaluatorConfig

POLICY_NAME = "device_status"
DEFAULTS = {
    "active_device_days": 7,
    "retire_review_days": 30,
    "patch_activity_days": 35,
    "reboot_pending_days": 3,
    "repeated_failure_count": 3,
    "approval_backlog_count": 25,
    "source_delay_hours": 8,
}


def get_device_status_policy(tenant_id: int = 1) -> dict[str, int]:
    """Return validated tenant policy without writing on read paths."""
    stored = (
        EvaluatorConfig.objects.filter(tenant_id=tenant_id, evaluator_name=POLICY_NAME)
        .values_list("config", flat=True)
        .first()
    )
    stored = stored if isinstance(stored, dict) else {}
    policy = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        try:
            value = int(stored.get(key, default))
        except (TypeError, ValueError):
            value = default
        policy[key] = max(1, min(value, 365 if key.endswith("days") else 10_000))
    # Review for retirement cannot come before a computer is offline.
    policy["retire_review_days"] = max(
        policy["retire_review_days"], policy["active_device_days"] + 1
    )
    return policy


# A client may set its own "offline after" days (``clients.offline_after_days``).
# Ingest applies it to lifecycle aging, the offline finding, stale agents and
# readiness (``ingest/device_status_settings.py``); these helpers apply the same
# rule to Operations readers so a page and its findings agree (PLAN-012 item 1).


def get_client_device_status_policy(client, tenant_id: int = 1) -> dict[str, int]:
    """Tenant policy with ``active_device_days`` replaced by the client's own value."""
    policy = get_device_status_policy(tenant_id)
    days = getattr(client, "offline_after_days", None) if client is not None else None
    if days:
        policy["active_device_days"] = int(days)
    return policy


def offline_days_sql(client_column: str, default_days: int) -> str:
    """SQL for the "offline after" days of the Computer whose client is ``client_column``."""
    return (
        "COALESCE((SELECT oc.offline_after_days FROM operations.clients oc "
        f"WHERE oc.id = {client_column}), {int(default_days)})"
    )


def recent_contact_sql(contact_column: str, client_column: str, default_days: int) -> str:
    """SQL predicate: last contact is within the Computer's effective offline window."""
    return (
        f"{contact_column} >= NOW() - make_interval(days => "
        f"{offline_days_sql(client_column, default_days)})"
    )


def stale_contact_sql(contact_column: str, client_column: str, default_days: int) -> str:
    """SQL predicate: no contact, or last contact older than the effective window."""
    return (
        f"({contact_column} IS NULL OR NOT "
        f"{recent_contact_sql(contact_column, client_column, default_days)})"
    )
