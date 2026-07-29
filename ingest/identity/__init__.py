"""Identity resolution.

Owns the definition of which observation streams constitute per-device
identity evidence.
"""

from __future__ import annotations

# Entity types whose observations establish per-device identity. Only these
# may be matched, linked into device_links, or promoted into a new Device.
#
# Maintained as an allowlist, not an exclusion list: a new entity type must
# opt in deliberately. Documentation sources (`doc.*`) carry no independent
# identity evidence — a Hudu card is a pointer to another vendor's record, and
# its asset name is documentation, not a hostname. Letting such rows reach the
# resolver would hostname-match them against real devices and promote the
# unmatched ones into Devices invented from a wiki page. `software` rows are
# device-scoped attributes; `org` rows resolve to clients, not devices.
IDENTITY_ENTITY_TYPES = frozenset({
    "agent.rmm",
    "agent.edr",
    "agent.remote_access",
    "vm.host",
    "vm.guest",
    "network.device",
    "monitor.target",
})
