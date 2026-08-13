"""Identity resolution.

Owns the definition of which observation streams constitute per-device
identity evidence — now read from `operations.entity_types`, not hardcoded.

Only these may be matched, attached to a device, or promoted into a new
Device. Documentation streams (`cmdb.*`) carry no independent identity: a CMDB
card is a pointer to another vendor's record and its asset name is
documentation, not a hostname. Letting such rows reach the resolver would
hostname-match them against real devices and promote the unmatched ones into
Devices invented from a wiki page.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Used only if the lookup runs before the table exists (a container started
# against a database that has not yet applied migration 0092). Deliberately
# identical to the pre-migration literal so behavior is unchanged in that
# window, and logged loudly when used.
_BOOTSTRAP_FALLBACK = frozenset({
    "agent.rmm",
    "agent.edr",
    "agent.remote_access",
    "vm.host",
    "vm.guest",
    "network.device",
    "monitor.target",
})

_cache: frozenset[str] | None = None


def identity_entity_types(cur: Any) -> frozenset[str]:
    """Entity types that establish per-device identity.

    Cached for the process lifetime: this is reference data read on every
    resolver pass, and a collection cycle must not re-query it per row.

    Never returns an empty set. An empty result would silently disable
    identity resolution entirely — every observation would look non-identity,
    nothing would resolve or promote, and no error would appear anywhere.
    """
    global _cache
    if _cache is not None:
        return _cache

    try:
        cur.execute(
            "SELECT name FROM operations.entity_types WHERE is_identity_signal"
        )
        names = frozenset(r[0] for r in cur.fetchall())
    except Exception:
        log.exception(
            "entity_types lookup failed — falling back to the built-in set. "
            "Identity behavior is unchanged, but the table is authoritative "
            "and should be repaired."
        )
        return _BOOTSTRAP_FALLBACK

    if not names:
        log.error(
            "operations.entity_types has no identity signals. Refusing to "
            "disable identity resolution; using the built-in set. Seed the "
            "table (migration 0092) or correct is_identity_signal."
        )
        return _BOOTSTRAP_FALLBACK

    _cache = names
    return _cache


def reset_cache() -> None:
    """Drop the cached set. For tests and for admin edits taking effect."""
    global _cache
    _cache = None
