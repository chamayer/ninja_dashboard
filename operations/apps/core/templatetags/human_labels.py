"""Template filters that translate internal identifiers into
operator-facing labels. Backend keeps DB / SQL / condition_key
strings untouched; this is display-only.

Usage in templates:

    {% load human_labels %}
    {{ finding_type.name|humanize_label }}

Rules:
- Unknown/unmapped values return the input unchanged (never break)
- Prefixed values (`policy-allowlist:X`, `default:server`) fall
  through a small parser so ad-hoc suffixes render nicely
"""

from __future__ import annotations

import re

from django import template

register = template.Library()


_LABELS: dict[str, str] = {
    # ── Finding types — patching ─────────────────────────────
    "device_never_patched": "Never patched",
    "patching_stalled": "Patching not progressing",
    "reboot_pending": "Awaiting reboot",
    "patch_failing_repeatedly": "Repeated install failures",
    "patch_approval_backlog": "Approval backlog",
    # ── Finding types — software ─────────────────────────────
    "suspicious_name": "Suspicious name",
    "install_path_suspicious": "Installed from suspicious location",
    "unauthorized_av": "Unauthorized AV product",
    "unauthorized_rmm": "Unauthorized RMM tool",
    "unauthorized_remote_access": "Unauthorized remote access tool",
    "multi_av_conflict": "Multiple AV products installed",
    "rare_recent": "Rare software",
    "eol_runtime": "End-of-life runtime",
    # ── Finding types — coverage / lifecycle ─────────────────
    "missing_required_platform": "Missing required platform",
    "stale_required_platform": "Platform not reporting",
    "device_offline": "Device offline",
    "device_stale_data": "No recent data",
    "device_unenrolled": "No agent installed",
    "duplicate_platform_record": "Duplicate source record",
    "source_failure": "Source not reporting",
    "device_missing_from_source": "Device missing from source",
    "device_role_conflict": "Device role changed",
    "device_long_offline": "Device offline (long)",
    "cross_client_conflict": "Cross-client name conflict",
    "unmapped_node_class": "Unknown device class from source",
    # ── Finding types — platform / identity health ───────────
    "identity_resolution_pending": "Awaiting identity resolution",
    "software_queue_stalled": "Software queue stalled",
    "stale_collector_binding": "Collector binding stale",
    "unlinked_external_identity": "External ID not linked to a device",
    # ── Finding types — client resolver ──────────────────────
    "client_name_conflict": "Client name changed at source",
    "client_link_collision": "Client name collision",
    "client_unattached_group": "Group not attached to a client",
    # ── Scope values ─────────────────────────────────────────
    "Included": "In scope",
    "Excluded": "Excluded",
    "Unmanaged": "Not managed",
    "Unknown": "Not determined",
    # ── Scope reasons (patching) ─────────────────────────────
    "no-ninja-link": "Not in Ninja RMM",
    "os-group-not-windows": "Not a Windows device",
    "device.patchingDisabled": "Excluded — device flagged in Ninja",
    "organization.patchingDisabled": "Excluded — organization flagged in Ninja",
    "location.patchingDisabled": "Excluded — location flagged in Ninja",
    "device.patchingEnabled": "Included — device override in Ninja",
    "device.workstationPatchingDisabled": "Excluded — workstation flagged in Ninja",
    "organization.workstationPatchingDisabled": "Excluded — org workstation flagged",
    "location.workstationPatchingDisabled": "Excluded — location workstation flagged",
    "device.serverPatchingDisabled": "Excluded — server flagged in Ninja",
    "organization.serverPatchingDisabled": "Excluded — org server flagged",
    "location.serverPatchingDisabled": "Excluded — location server flagged",
    # ── Entity types ─────────────────────────────────────────
    "agent.rmm": "RMM agent",
    "agent.edr": "EDR agent",
    "agent.remote_access": "Remote access agent",
    "vm.guest": "Virtual machine",
    "vm.host": "Hypervisor host",
    "network.device": "Network device",
    "monitor.target": "Monitored target",
    "org": "Organization",
    "software": "Software",
    # ── Match methods (identity) ─────────────────────────────
    "serial": "By serial number",
    "vm_uuid": "By VM UUID",
    "hostname_strict": "By hostname (strict)",
    "hostname_loose": "By hostname (fuzzy)",
    "manual": "Manual match",
    "promoted": "Auto-promoted",
    "bootstrap": "Initial import",
    # ── Device roles ─────────────────────────────────────────
    "server": "Server",
    "workstation": "Workstation",
    "unknown": "Not determined",
    # ── OS groups ────────────────────────────────────────────
    "Windows": "Windows",
    "macOS": "macOS",
    "Linux": "Linux",
    "Other": "Other",
    # ── Finding categories ───────────────────────────────────
    "patching": "Patching",
    "coverage": "Coverage",
    "identity": "Identity",
    "platform": "Platform health",
    "resolver": "Client resolver",
}


_PREFIX_TEMPLATES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^default:(.+)$"),
     "Default for {} devices"),
    (re.compile(r"^policy-allowlist:(.+)$"),
     "Included via policy: {}"),
]


@register.filter(name="humanize_label")
def humanize_label(value):
    """Render an internal identifier as an operator-friendly label.

    Returns the input unchanged when no mapping is known — never
    raises. Handles a small set of prefixed patterns for scope
    reasons that carry a runtime suffix.
    """
    if value is None:
        return ""
    key = str(value)
    if key in _LABELS:
        return _LABELS[key]
    for pattern, tmpl in _PREFIX_TEMPLATES:
        m = pattern.match(key)
        if m:
            arg = m.group(1)
            # Recursively humanize the suffix so
            # `default:workstation` → "Default for Workstation devices"
            arg_labelled = _LABELS.get(arg, arg)
            return tmpl.format(arg_labelled.lower() if tmpl.endswith(" devices") else arg_labelled)
    return key


@register.filter(name="humanize_scope_reason")
def humanize_scope_reason(value):
    """Alias — same behavior as humanize_label. Present so templates
    can be self-documenting about what they're rendering.
    """
    return humanize_label(value)
