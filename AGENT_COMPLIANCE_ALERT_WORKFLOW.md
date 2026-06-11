# Agent Compliance Alert Workflow

Date: 2026-06-11

## Purpose

Define what qualifies as an alert in Agent Compliance, at every level.

The intent is to keep the dashboard actionable:

- operator alerts for device-level problems;
- admin alerts for org/config problems;
- source alerts for collector health;
- system alerts for pipeline failures;
- no spam for unchanged or non-actionable noise.

## Workflow

1. Collect raw observations.
2. Resolve observations to clients and orgs.
3. Build or refresh org alignment.
4. Evaluate the compliance matrix.
5. Derive findings from the matrix and source health.
6. Deduplicate against prior state.
7. Route only state changes and important recoveries.
8. Show the same state in Metabase with concise human labels.

## Alert Levels

### Device Alert

Device alerts are the primary operator workload.

Trigger examples:

- missing required platform combo;
- stale required platform;
- degraded device;
- cross-client or wrong-tenant conflict;
- `NO AV` exemption not present when expected to be present;
- device-level finding changed severity or combo.

What it should look like:

- one row per device finding;
- plain English summary;
- combo-based, not one alert per platform if the combo is the same;
- clear next action.

Typical route:

- operator dashboard;
- email for notable issues;
- Zendesk when human follow-up is needed.

### Org Review Alert

Org review items are admin/operator config work, not device remediation.

Trigger examples:

- new alignment mismatch;
- new unresolved org name;
- alias missing for a known org;
- exclude candidate that should be suppressed;
- fuzzy alignment that needs confirmation.

What it should look like:

- one row per org name or candidate mapping;
- show the missing or conflicting platform name;
- suggest the next action:
  - add alias;
  - exclude org;
  - review source naming.

Typical route:

- Org Review dashboard;
- admin email summary;
- Zendesk only if someone needs to own cleanup.

These should not page the operator repeatedly by default.

### Source Alert

Source alerts are collector health issues.

Trigger examples:

- source run failed;
- source timed out;
- source rate-limited;
- source returned zero rows unexpectedly;
- source health changed from ok to failed;
- source health recovered from failed to ok.

What it should look like:

- source name;
- platform;
- status;
- rows observed;
- error text trimmed to the useful part;
- whether compliance coverage is affected.

Typical route:

- Source Health dashboard;
- admin/system email;
- Zendesk when vendor/support action is needed.

Source failure should suppress false missing-platform alerts for that
source rather than flooding the operator with bad downstream findings.

### System Alert

System alerts are platform failures in the agent-compliance stack
itself.

Trigger examples:

- scheduler did not fire;
- ingest run crashed;
- migration failed;
- Metabase bootstrap failed;
- alert delivery failed;
- config sync failed.

What it should look like:

- component name;
- failure type;
- last success time;
- current impact.

Typical route:

- admin/system dashboard;
- email to the service owner;
- incident ticket if the failure persists.

## What Is Not An Alert

These are dashboard review items, not alerts by themselves:

- unchanged alignment mismatches;
- unchanged unresolved observations;
- known excludes that are already filtered;
- raw observation noise with no action needed;
- repeated findings that have already been acknowledged and are
  unchanged inside cooldown.

## Dedupe Rules

Use dedupe to keep alerts stable.

Suggested key dimensions:

- client;
- hostname;
- finding type;
- missing platform combo;
- source scope;
- severity band.

Alert state should record:

- first seen;
- last seen;
- last routed;
- current status;
- route used;
- resolution time.

## Presentation Rules

Alert rows should be human-readable:

- no schema names in the default view;
- no raw JSON in the default view;
- no quoted bracketed lists unless the debug view is active;
- keep summaries short;
- keep the next action visible.

The debug view can show the raw fields.

## Recommended Default Routes

1. Device alerts -> operator email + dashboard.
2. Org review items -> admin dashboard + summary email.
3. Source alerts -> admin/system email + dashboard.
4. System alerts -> admin/system email + ticket.

Ninja should remain optional as an alert route because the platform
itself can be the thing that is missing or unhealthy.

