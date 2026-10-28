# PLAN-033 — Patching and device-health reporting gaps

**Status: deferred.** Registered 2026-10-28 from the backlog. Building any
step needs the user's approval; registering it authorizes nothing.

## Goal

Show in Operations the patching and device-health information Metabase used
to show and Operations still lacks, then retire the 8 Metabase-era ingest
views that only back these gaps.

## Evidence

[PLAN-022 view review](../records/PLAN-022-legacy-cleanup/metabase-view-capability-review.md)
and the corrected [parity audit](../../operations/docs/metabase-parity-audit.md)
(rows marked **Missing**). ADR 0005 applies: build from generic contracts and
current data, not by copying Metabase SQL.

## Items

| Step | Gap | Data today |
| --- | --- | --- |
| 1 | Decide what operators need from each gap below, especially device health | — |
| 2 | Patch warning analysis: warnings by category and day, top devices by warnings, a "with warnings" filter | `ninja_activities.activities` (`PATCH_MANAGEMENT_MESSAGE`, `SOFTWARE_PATCH_MANAGEMENT_MESSAGE`); categorized now by `ninja_activities.patch_warning_events_recent` |
| 3 | `/patching/trends/` additions: system reboots per day, operational failures per day (`PATCH_MANAGEMENT_FAILURE`), MANUAL patches by age | `ninja_activities.activities` and `system_reboot_events_recent`; MANUAL state in `ninja_patches` |
| 4 | Ninja device health: threats, vulnerability counts, alerts, health status, pending-reboot reason | Collected by `ingest/core/device_health.py`; `operations.ninja_device_health_current_shadow` |
| 5 | Drop the 8 views once each gap is built or declined; first check whether `device_troubleshooting_signal` still refreshes (row estimate −1 on 2026-10-28) | Review record |

## Dependencies

Activity retention (received by PLAN-019 on 2026-10-28) bounds how far back
the activity trends can reach. The patching conditions in
`shared/conditions/profile.json` already cover most of the troubleshooting
signal; extend them rather than adding a parallel label.

## Next action

User decision on Step 1.
