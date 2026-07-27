"""Tenant policy for device status and patching posture."""

from __future__ import annotations

from .models import EvaluatorConfig

POLICY_NAME = "device_status"
DEFAULTS = {
    "active_device_days": 7,
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
    return policy
