# Agent Compliance Rebuild Blueprint

Date: 2026-06-11

## Goal

Build a human-first dashboard from a clean design, not by layering more fixes onto the current screens.

The dashboard should answer one question quickly:

> What needs a person to do right now?

It should not force a person to understand the internal plumbing first.

## Core Rules

1. No raw URLs in visible table fields.
2. Visible actions must use short human labels.
3. If a link exists, it should live behind the label, not in the data.
4. The default view should be concise and readable.
5. Debug detail belongs in a separate view.
6. Placeholder names are noise unless explicitly reviewed.
7. Canonical orgs are not created from random observations.
8. Device ignore/restore must remain reversible and visible.
9. Vendor ingest collects facts; compliance evaluation decides what
   those facts mean for the current configuration.

## Compliance Evaluation Model

Agent Compliance has two paths:

- Full collection: scheduled every few hours and calls Ninja,
  SentinelOne, LogMeIn, and ScreenConnect.
- Evaluate-only: reloads the latest successful stored observations per
  source, re-applies current customer aliases and requirements, then
  rebuilds the current compliance matrix and device findings.

Dashboard configuration actions should use evaluate-only whenever the
underlying vendor facts did not change. Examples: changing required
platforms, approving a customer name, adding an alias, excluding a
placeholder name, changing stale thresholds, or ignoring/restoring a
device.

This keeps the UI responsive without turning every button click into a
vendor API collection run.

## What Metabase Should Show

### Home

This is the landing page.

It should show:
- how many devices need attention;
- how many source problems exist;
- how many names need mapping;
- how many items are intentionally ignored.

These should be plain labels, not metric jargon.

Recommended labels:
- Today
- Devices
- Alerts
- Customers
- Setup
- Health
- Debug

### Devices

This is the operator queue.

It should show:
- device;
- org;
- what is missing;
- current state;
- one clear action.

The table should be short and obvious.

### Customers

This is not the primary queue.

It is for real names that need a decision:
- fix alias;
- skip placeholder noise;
- review a new name;
- confirm a mismatch.

It should not be polluted by placeholders or leftover audit rows.

In the rebuilt dashboard, customer-name work belongs in a supporting
workflow, not in the daily device queue. The main operator path is:

1. Today for the summary.
2. Devices for device work.
3. Alerts for notifications and delivery state.
4. Customers for name review and aliases.
5. Setup for requirements and alert enablement.
6. Health for source health and data confidence.
7. Debug for leftovers and admin-only cleanup.

### Alerts

This is the notification operations page.

It should show:
- notifications ready to send;
- open issues that are not notifying and why;
- recent delivery attempts;
- open device issues as supporting context.

Alert configuration does not belong at the top of this page. It belongs
in Setup.

### Setup

This is the control page.

It should show:
- required platforms by customer and device scope;
- customer alert enablement;
- alert rules;
- notification routes;
- source setup.

Changing configuration belongs here, not on the daily operator pages.

### Health

This is the source health view.

It should show:
- source;
- platform;
- status;
- rows observed;
- issue text;
- mapping work only if it helps explain the source state.

If a mapping table lives anywhere visible, it belongs here as a compact support table, not as a second review page.

### Debug

This is the escape hatch.

It can show:
- raw observations;
- alignment leftovers;
- candidate noise;
- excluded names;
- source-level details.

Nothing in Debug should be required for normal operator work.

## Action Design

Action labels should be short:
- `Fix N`
- `Fix S1`
- `Fix LMI`
- `Skip`
- `Restore`
- `Ignore`

The visible result should read like a work item, not a URL.

If Metabase cannot reliably hide URLs on hover in a table cell, then the link must not be placed in the field.
Use either:
- Metabase click behavior;
- a separate action page;
- or a dedicated action panel.

For the rebuild, the preferred pattern is:
- keep the table value as a short label;
- attach the URL in click behavior, not the SQL output;
- let the browser reveal the target only when the operator hovers or clicks.

Raw URLs should never be selected as visible data.

## Alert Design

Alerts should only come from meaningful current-state queues:
- device issues;
- source failures;
- system failures.

Alerts should not come from leftover mapping noise.

## Data Model Expectations

The rebuild should keep these ideas separate:

- canonical org registry;
- platform aliases;
- candidate names;
- ignored names;
- ignored devices;
- current device findings;
- notification readiness;
- source health;
- debug leftovers.

The dashboard should read from those clean layers, not from one overloaded table.

## Acceptance Criteria

The rebuild is acceptable when:

1. The nav is simple and obvious.
2. The device queue is readable at a glance.
3. The mapping queue only contains real work.
4. Placeholder names are not part of the main flow.
5. No table field shows a raw action URL.
6. Debug still exposes the raw data when needed.
