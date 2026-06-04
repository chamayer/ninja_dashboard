# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Make filters actually reach the device cards on Command Center,
Overall Patching Status, Org Overview, and Device Patching Status.

## Why

Operator-reported. After v0.14.1 + v0.14.2 added Org/Severity/OS
filters to high-level dashboards, the device cards still don't
narrow when filters change. Patch cards (which use the FULL
mappings) seem to work — only device cards don't.

## Investigation

Compared tags vs mappings per dashboard:

| Dashboard | _TAGS | _PARAM_MAPPINGS (device) | _PARAM_MAPPINGS_FULL (patch) | Patch Detail (works) |
|---|---|---|---|---|
| Command Center | 3 (org, device_type, severity) | 2 (org, device_type) — mismatch | 3 (match) | n/a |
| Overall | 4 (org, dt, os, sev) | 3 (org, dt, os) — mismatch | 4 (match) | n/a |
| Org Overview | 4 (org, dt, os, sev) | 3 (org, dt, os) — mismatch | 4 (match) | n/a |
| Trends | 4 (days, org, dt, sev) | 3 (days, org, dt) — mismatch | 4 (match) | n/a |
| Patch Detail | 8 | n/a | 8 (match) | **WORKS** |
| PCOV | 5 | n/a | 5 (match) | broken per user |

Pattern: **whenever a card declares more template tags than its
dashcard parameter_mappings, Metabase silently breaks all filter
binding on that card.** Patch Detail uses identical 8/8 tags+mappings
and works. Device cards on the 3 above have 3 tags / 2 mappings
(or similar), and they don't honor filters.

PCOV is the outlier — its tags and mappings match (5/5) yet user
reports same symptom. Need separate investigation.

## Scope

**In:**
- Switch all device-card `param_mappings` keys to the FULL mapping
  on Command Center, Overall, Org Overview, and Trends so they
  match the declared TAGS exactly.
- The extra mappings (e.g. severity on a device card) are benign —
  Metabase will wire a parameter that the SQL never references.

**Out / separate investigation:**
- PCOV device cards. Need to read what's actually in Metabase.

## Files to change

- `ingest/metabase_bootstrap.py`
    - Command Center: change `_CMD_PARAM_MAPPINGS` → `_CMD_PARAM_MAPPINGS_FULL`
      on device-only cards (cmd_active_devices, cmd_patching,
      cmd_stale, cmd_never, cmd_awaiting_reboot, cmd_recent_activity).
    - Overall: same change on active_devices, ov_pcov_*, needs_reboot.
    - Org Overview: same change on org_active_devices, org_stale,
      org_never, org_patching, org_reboot_devices.
    - Trends: same change on trends_reboots_daily,
      trends_active_devices (the others already use FULL).

## Steps

1. Apply the param_mapping swap across the four dashboards.
2. Compile-check.
3. Bump VERSION → 0.14.3, update CHANGELOG / SESSIONS, commit + push,
   report hash.

## Status

*done* — v0.14.3. PCOV-broken question separate; will follow up if
fix doesn't address it.
