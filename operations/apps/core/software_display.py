"""Resolve canonical software keys to the latest spelling reported by Ninja."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import connection, transaction


def preferred_software_display_names(names: Iterable[str]) -> dict[str, str]:
    """Map canonical keys to their latest retained, nonempty Ninja display name.

    The current installation rows retain stale installations, so their last
    reported source spelling remains available for findings and decision logs
    after a product is removed. Callers keep the canonical value for all keys,
    filters, and links; a missing map entry falls back to that value.
    """
    keys = sorted({str(name).strip().lower() for name in names if str(name).strip()})
    if not keys:
        return {}

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            SELECT DISTINCT ON (lower(canonical_name)) lower(canonical_name), display_name
              FROM operations.software_installations_current
             WHERE tenant_id = 1
               AND lower(canonical_name) = ANY(%s::text[])
               AND display_name <> ''
             ORDER BY lower(canonical_name), last_observed_at DESC,
                      display_name, device_id
            """,
            [keys],
        )
        return {key: display_name for key, display_name in cur.fetchall()}


def software_display_name(name: str, names: dict[str, str]) -> str:
    """Return a preferred source label, falling back to the supplied key."""
    return names.get(str(name).strip().lower(), name)
