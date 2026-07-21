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
    "missing_required_platform": "Required agent not installed",
    "stale_required_platform": "Required agent not checking in",
    "device_offline": "Device offline",
    "device_stale_data": "No recent data",
    "device_unenrolled": "No management agent installed",
    "duplicate_platform_record": "Duplicate device record",
    "source_failure": "Data source not responding",
    "device_missing_from_source": "Device removed from inventory",
    "device_role_conflict": "Device role changed",
    "device_long_offline": "Offline for an extended period",
    "cross_client_conflict": "Same hostname on two clients",
    "unmapped_node_class": "Unrecognized device type",
    # ── Finding types — platform / identity health ───────────
    "identity_resolution_pending": "Awaiting device identity match",
    "software_queue_stalled": "Software scan queue stalled",
    "stale_collector_binding": "Ingest connector stopped",
    "unlinked_external_identity": "Unresolved device from source",
    # ── Finding types — client resolver ──────────────────────
    "client_name_conflict": "Client renamed at source",
    "client_link_collision": "Multiple clients claim this name",
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
    # ── Software catalog categories ──────────────────────────
    "av": "Antivirus",
    "edr": "EDR",
    "rmm": "RMM",
    "remote_access": "Remote access",
    "browser": "Web browser",
    "runtime": "Runtime",
    "eol": "End-of-life",
    "system": "System tool",
    "productivity": "Productivity",
    "developer": "Developer tool",
    # ── Software decision values ─────────────────────────────
    "approve": "Approved",
    "approve_publisher": "Publisher approved",
    "reject": "Rejected",
    "investigate": "Investigating",
    # ── Portfolio state buckets (Dashboard) ──────────────────
    "critical": "Critical",
    "degrading": "Degrading",
    "healthy": "Healthy",
    "no_data": "No data",
    # ── Client health traffic light (Dashboard) ──────────────
    "red": "Attention needed — critical finding open",
    "amber": "Watching — high-severity finding open",
    "green": "Healthy",
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


@register.simple_tag(name="finding_detail_text")
def finding_detail_text(finding):
    """Compact per-type detail string for a Finding.

    Mirrors the `_detail_string` helper in `findings_queue`. Keeps
    surfaces (device_detail Issues tab, findings_queue) rendering
    the same information for the same finding type without each
    template inventing its own copy.
    """
    d = getattr(finding, "finding_details", None) or {}
    name = getattr(getattr(finding, "finding_type", None), "name", None) or ""

    if name == "missing_required_platform":
        return f"missing {d.get('platform', '?')}"
    if name == "stale_required_platform":
        hours = d.get("gap_age_hours") or d.get("gap_hours")
        base = f"stale {d.get('platform', '?')}"
        return f"{base} · {int(hours)}h" if hours else base
    if name == "device_unenrolled":
        ps = d.get("power_state") or "unknown"
        days = d.get("days_since_last_seen")
        via = d.get("observed_via") or "tracked"
        parts = [ps]
        if days is not None:
            parts.append(f"{days}d")
        parts.append(f"via {via}")
        return " · ".join(parts)
    if name in ("device_offline", "device_long_offline"):
        since = (
            d.get("fully_offline_since")
            or d.get("last_contact_at")
            or d.get("last_seen_at")
        )
        last_src = d.get("last_seen_source")
        base = f"offline since {since[:10]}" if since else "no source has contact"
        return f"{base} (last: {last_src})" if last_src else base
    if name == "device_role_conflict":
        return f"{d.get('previous_role', '?')} → {d.get('new_role', '?')}"
    if name == "device_missing_from_source":
        return f"removed from {d.get('platform', '?')}"
    if name == "device_never_patched":
        return "no INSTALLED patches on record"
    if name == "patching_stalled":
        ls = d.get("last_patch_seen_at")
        return f"last install {ls[:10]}" if ls else "no fresh scan (>35d)"
    if name == "reboot_pending":
        lb = d.get("last_boot_at")
        return f"last boot {lb[:10]}" if lb else "no boot recorded"
    if name == "patch_failing_repeatedly":
        kbs = d.get("failing_patches") or []
        return f"{len(kbs)} KB(s) failing"
    if name == "patch_approval_backlog":
        return f"{d.get('backlog_count', '?')} approved uninstalled"
    if name == "placeholder_serial":
        serial = d.get("serial", "")
        return f"serial: {serial}" if serial else "placeholder serial"
    if name == "shared_serial":
        count = d.get("device_count")
        return f"{count} devices share serial {d.get('serial', '')}" if count else "shared serial"
    if name == "placeholder_mac":
        macs = d.get("junk_macs") or []
        return ", ".join(macs) if macs else "junk MAC"
    if name == "identity_conflict":
        n = d.get("candidate_count")
        return f"{n} candidates share hostname {d.get('hostname', '')}" if n else "hostname collision"
    if name == "duplicate_platform_record":
        return f"duplicate {d.get('platform', '?')} record"
    if name == "rare_recent":
        n = d.get("machine_count")
        return f"on {n} machines" if n else "rare install"
    if name == "unmatched_source_group":
        return f"source group {d.get('external_id', '?')}"
    if name == "unnamed_source_group":
        return f"binding {d.get('source_binding_id', '?')[:8]}…"
    # Fallback: platform if present, else empty
    return d.get("platform") or ""


@register.simple_tag(name="finding_display_label")
def finding_display_label(finding):
    """Composed operator-facing label for a Finding.

    Adds the specific agent product to `missing_required_platform` /
    `stale_required_platform` labels so operators see *which* agent
    is missing at a glance instead of the generic
    "Required agent not installed". Also appends
    "(device offline)" when the evaluator downgraded the finding
    because the whole device is offline.
    """
    ft_name = getattr(getattr(finding, "finding_type", None), "name", None) or ""
    details = getattr(finding, "finding_details", None) or {}
    base = _LABELS.get(ft_name, ft_name)

    platform = details.get("platform")
    if platform and ft_name in (
        "missing_required_platform", "stale_required_platform",
    ):
        base = f"{base}: {platform}"

    if details.get("reason_suppressed") == "device_offline":
        base = f"{base} (device offline)"

    return base


@register.filter(name="humanize_scope_reason")
def humanize_scope_reason(value):
    """Alias — same behavior as humanize_label. Present so templates
    can be self-documenting about what they're rendering.
    """
    return humanize_label(value)
