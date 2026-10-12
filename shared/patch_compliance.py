"""Shared patch-compliance semantics for Operations and legacy reporting."""

from __future__ import annotations

COMPLIANCE_MISSING_STATUSES = ("APPROVED", "MANUAL", "FAILED", "PENDING")


def excluded_patch_categories(raw_value: str | None) -> tuple[str, ...]:
    """Return the configured patch categories excluded from compliance views."""
    return tuple(
        value.strip()
        for value in (raw_value or "").split(",")
        if value.strip()
    )
