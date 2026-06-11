# Agent Compliance Operator UI Contract

Date: 2026-06-11

## Purpose

This document defines the human-facing dashboard shape for Agent
Compliance before more code is built.

The goal is a dashboard that an operator can navigate quickly:

- clear calls to action;
- no raw schema language in primary views;
- concise table cells;
- operator work first, admin work second, debug third.

## Audience Split

### Operator

Operator views are device-level and action-oriented.

They answer:

- which devices are missing something;
- which devices are stale or degraded;
- which devices need follow-up now;
- which source is failing right now.

Operator actions should be short and obvious:

- open device;
- review finding;
- add alias;
- exclude org;
- acknowledge source issue.

For v1, the Add alias and Exclude org actions are exposed as explicit
links from the Org Review dashboard and unresolved-observation rows.
The ingest service owns the write-back endpoints; Metabase stays the
navigation and review surface.

### Admin

Admin views are org-level and system-level.

They answer:

- which org names are not aligning cleanly;
- which aliases exist;
- which exclusions exist;
- which platform source is failing;
- which client/source config needs maintenance.

Admin actions should change configuration, not device state.

## Navigation Model

Use the same top navigation pattern already used by patching:

- fixed nav bar at the top of the dashboard;
- short labels;
- current page highlighted;
- sibling dashboards linked from the nav bar.

Recommended dashboard set:

1. Command Center
2. Devices
3. Org Review
4. Source Health
5. Debug

The primary landing page should be the Command Center.

## Display Rules

Primary tables and cards must follow these rules:

- show only the fields an operator needs first;
- avoid raw JSON in primary tables;
- avoid quoting values unless the value itself requires it;
- avoid bracketed lists in primary tables;
- keep labels short and plain;
- prefer human names over schema names;
- hide IDs unless the user is in Debug.

Examples:

- use `Needs review` instead of `MISMATCH`;
- use `Needs alias` instead of `overall_status = MISMATCH`;
- use `No matching client` instead of `resolved_client_id is null`;
- use `Source offline` instead of `status = failed`;
- use `Stale` instead of `is_stale = true`;
- use `Degraded` instead of `is_degraded = true`.

## Primary Dashboard Content

The primary dashboard should show:

- overall compliance;
- noncompliant device count;
- active findings;
- source health;
- devices needing action;
- orgs needing review;
- unresolved observations that need aliasing.

The primary tables should be concise and operator-readable.

Suggested visible columns:

- Org
- Device
- Platform
- Status
- Missing
- Last seen
- Source

Suggested hidden or secondary fields:

- raw IDs;
- raw platform group name;
- raw JSON payload;
- internal match markers;
- merge candidates;
- debug notes.

## Admin / Review Dashboard Content

The admin review dashboard should show:

- alignment mismatches;
- alias candidates;
- excludes;
- source setup;
- per-client platform requirements;
- source-run failures;
- unresolved mappings.

This dashboard can be more verbose than the primary view, but still
should not dump raw payloads by default.

## Debug Dashboard Content

Debug is the only place where raw details should be the default.

It can include:

- raw observation JSON;
- source IDs;
- group IDs;
- device IDs;
- parser markers;
- mapping notes;
- run IDs and timestamps.

Debug should not be the default landing page.

## Calls To Action

Primary CTAs should be short and consistent:

- Add alias
- Exclude org
- Open device
- Review source
- Refresh data
- Mark resolved

If a CTA is only relevant to admin/config work, keep it on the
admin/review dashboards rather than the operator home page.

## Terminology

Use human language in UI labels:

- `Command Center` for the main landing page;
- `Devices` for device-level findings;
- `Org Review` for alignment and alias work;
- `Source Health` for platform collector status;
- `Debug` for raw data and internal state.

Avoid exposing raw database terms in the main UI:

- no `org_alignment_current` labels;
- no `platform_observations` labels;
- no `resolved_client_id` labels;
- no `missing_required_platforms` labels.

Those terms can remain in SQL and debug views.
