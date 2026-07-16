# Ninja Dashboard current state

Status date: 2026-07-16
Repository version observed: 0.50.5

## Runtime

The Compose stack currently contains:

- Custom Postgres image
- Metabase
- Python ingest service
- Django Operations service

The ingest API and Operations health interface are intended for controlled
operator access; Postgres is not directly published.

## Implemented ingest domains

- Shared Ninja core entities and custom fields
- Patch state and install outcomes
- Filtered activity/event history
- Agent/compliance connectors and legacy schema
- Cross-source identity and client resolution
- Inventory and software refresh queues
- Metabase bootstrap and reporting materializations

## Implemented Operations capabilities

- Fleet and client views
- Device list/detail
- Findings and administrative finding health
- Patching queue and device patching context
- Source health
- Client and identity candidate review
- Coverage profiles and client policies
- Software decisions
- Notification rules and suppressions
- Canonical/derived/operator/effective device-state layers

## Current release direction

Releases 0.45.0 through 0.50.1 added the Operations Patching page, device
patching detail, population/scope drilldown, role and client filters,
operator-friendly labels, and removal of the experimental enhanced-select
assets and vestigial header client picker in favor of native filters. Version
0.48.1 added fleet-wide device/client search in the header, and 0.48.2
reworked dashboard hero tiles around operational domains and improved Client
Health search and pagination. Versions 0.49.0 through 0.50.1 consolidated
navigation and reframed the dashboard around an MSP client portfolio, including
compact health filters and a multi-domain "clients on fire" exception panel.
Version 0.50.2 standardized operator-facing terminology on Issues/Items while
retaining internal finding model and route names. Versions 0.50.3 and 0.50.4
tightened the severe multi-domain attention panel and restored compact
click-through overview cards. Version 0.50.5 expanded the attention list in a
scrollable panel and clarified the Devices overview label.

The current CHANGELOG identifies the next design direction as:

- Client-detail and Review/Config/System workflow consolidation
- Fleet-wide software workflow improvements
- Further device-detail and bulk-action work
- Data-backed trends, contract/QBR context, assignments, and service metrics

This direction is not represented in the existing root BLUEPRINT or
Operations BUILD_BLUEPRINT; both describe older completed work.

## Current local state

- No tracked application changes were present when version 0.50.5 was
  observed.
- An API reference PDF is untracked.
- `operations/.claude/settings.local.json` exists, is untracked, and is
  currently ignored.
- These local artifacts are not active implementation evidence.

## Known incomplete areas

- Legacy `ingest/agent_compliance` and its schema remain pending cutover and
  destructive retirement.
- The root TODO and Operations TODO contain completed items presented as open
  and no longer accurately represent current priorities.
- Some Operations runbooks remain placeholders.
- The removed header client picker left a vestigial `client_switch` view and
  route scheduled for later Wave B cleanup.
- Current architecture and requirements are spread across CONTEXT,
  REQUIREMENTS, Operations DESIGN/BLUEPRINT, sessions, TODOs, and CHANGELOG.

## Authority

- Current behavior: code, migrations, generated dashboards, and tests/checks.
- Current release: root VERSION and CHANGELOG.
- Root architecture: `docs/architecture.md`.
- Operations concise architecture guide: `operations/docs/architecture.md`.
- Operations detailed architecture during transition: `operations/DESIGN.md`.
- Active work: the applicable `.work/plan.md`.
