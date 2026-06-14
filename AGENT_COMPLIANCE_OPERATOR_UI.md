# Agent Compliance UI Contract

Date: 2026-06-11

## Purpose

This document defines the human-facing dashboard shape for Agent
Compliance before more code is built.

The goal is a dashboard that a person can navigate quickly:

- clear calls to action;
- no raw schema language in primary views;
- concise table cells;
- device work first, setup work second, debug third.

## Audience Split

### Main View

Main views are device-level and action-oriented.

They answer:

- which devices are missing something;
- which devices are stale or degraded;
- which devices need follow-up now;
- which source is failing right now.

Actions should be short and obvious:

- open device;
- review finding;
- ignore device;
- restore device;
- add alias;
- exclude org;
- acknowledge source issue.

For v1, the Add alias and Exclude org actions are exposed as explicit
links from the Review dashboard and unresolved-observation rows.
The ingest service owns the write-back endpoints; Metabase stays the
navigation and review surface.

### Setup View

Setup views are org-level and system-level.

They answer:

- which org names are not aligning cleanly;
- which aliases exist;
- which exclusions exist;
- which platform source is failing;
- which client/source config needs maintenance.

Setup actions should change configuration, not device state.

## Navigation Model

Use the same top navigation pattern already used by patching:

- fixed nav bar at the top of the dashboard;
- short labels;
- current page highlighted;
- sibling dashboards linked from the nav bar.

Recommended dashboard set:

1. Today
2. Devices
3. Alerts
4. Customers
5. Setup
6. Health
7. Debug

The primary landing page should be Today.

## Display Rules

Primary tables and cards must follow these rules:

- show only the fields a person needs first;
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

The primary tables should be concise and human-readable.

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

## Setup / Review Dashboard Content

The setup review dashboard should show:

- per-client platform requirements;
- customer alert enablement;
- alert rules;
- notification routes;
- source setup.

The customer-name review dashboard should show:

- new customer names found;
- suggested customer aliases;
- manual alias action;
- ignored customer names;
- customer/platform name directory.

Setup changes configuration. Customer-name review changes mapping.
Device pages should not require either workflow for daily remediation.

## Alerts Dashboard Content

The alerts dashboard should show:

- notifications ready to send;
- open issues that are not notifying and why;
- recent notification delivery attempts;
- open device issues as supporting context.

Alert rules and per-customer alert setup belong in Setup, not at the top
of Alerts.

## Health Dashboard Content

The health dashboard should show:

- source-run failures;
- delivery failures;
- source rows observed;
- whether device coverage data can be trusted;
- unresolved-name volume by platform.

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
- Ignore device
- Restore device
- Open device
- Review source
- Refresh data
- Mark resolved

If a CTA is only relevant to setup/config work, keep it on the
setup/review dashboards rather than the main page.

## Terminology

Use human language in UI labels:

  - `Today` for the main landing page;
  - `Devices` for device-level findings;
  - `Health` for platform collector status and new-name review;
  - `Debug` for raw data, leftovers, and admin-level mapping cleanup.

Avoid exposing raw database terms in the main UI:

- no `org_alignment_current` labels;
- no `platform_observations` labels;
- no `resolved_client_id` labels;
- no `missing_required_platforms` labels.

Those terms can remain in SQL and debug views.
