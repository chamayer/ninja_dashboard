# Operations current state

Status date: 2026-07-16
Stack version observed: 0.50.5

## Implemented platform layers

- Tenant-aware canonical clients and devices
- Source/client and source/device links
- Cross-source observations and identity resolution
- Client candidates and mapping workflows
- Requirement profiles and coverage requirements
- Derived presence and session state
- Operator decisions and effective `v_device` state
- Domain-specific patching scope and override
- Findings, administrative findings, lifecycle, acknowledgement, and
  suppressions
- Notification rules, routes, state, events, and dispatch/digest paths
- Software decisions and software refresh queue
- Patching findings including reboot-pending

## Implemented UI

- Fleet/client dashboard and device navigation
- Device detail
- Issues/findings and administrative health
- Patching queue with population, scope, role, client, and status filters
- Source health
- Client and identity candidate review
- Coverage profiles and client policy
- Software decision workflows
- Notification rules and suppressions
- API schema and documentation

## Current architecture state

- The four-layer storage pattern is implemented for device session,
  exemptions/operator decisions, effective device reads, and patching scope.
- Source-specific raw data remains outside canonical Operations structures.
- Identity and client resolution use candidate/review paths for ambiguity.
- Runtime access is RLS-protected and tenant-aware.
- Legacy agent-compliance machinery still exists pending cutover.

## Current UI direction

Recent releases completed the first Patching workflow, a human-label/filter
foundation, removal of the vestigial header client picker, and the first
fleet-wide device/client search slice. Version 0.48.2 also reworked dashboard
hero tiles around operational domains and improved Client Health search and
pagination. Versions 0.49.0 through 0.50.1 consolidated navigation and
reframed the dashboard around an MSP client portfolio, compact health filters,
and multi-domain exception triage. Version 0.50.2 standardized operator-facing
terminology on Issues/Items while retaining internal finding model and route
names. Versions 0.50.3 and 0.50.4 tightened the severe multi-domain attention
panel and restored compact click-through overview cards. Remaining candidate
directions include:

1. Review/Config/System workflow consolidation
2. Fleet-wide software workflow improvements
3. Client-detail expansion
4. Device-detail expansion
5. Bulk issue/review actions and policy overrides
6. Trends and service context after the necessary data exists

The `client_switch` view and route remain as known cleanup after the header
picker removal.

This sequence is planning material, not yet an approved active task.

## Stale state documents

- BUILD_BLUEPRINT describes an older fleet-overview slice already committed.
- Root BLUEPRINT describes M0 work completed many releases ago.
- Operations TODO still presents completed Track O and Track C work as open.
- Operations SESSIONS contains valuable reasoning but is too large and
  chronological to be standing context.

## Local artifacts

- `operations/.claude/settings.local.json` exists, is untracked, and is
  ignored.
- It is machine-local configuration, not project state.

## Latest completed work

- Version 0.50.5 expanded the severe multi-domain client list to 30, contained
  it in a scrollable panel, displayed its count, and clarified the Devices
  overview label.
- The owning workflow recorded release commit `122a303`; independent
  validation was not rerun during the documentation organization review.

## Authority

- Implemented behavior: code and Django/SQL migrations.
- Concise architecture guide: `operations/docs/architecture.md`.
- Detailed architecture during transition: `DESIGN.md`.
- Stack release: root VERSION and CHANGELOG.
- Active work: `operations/.work/plan.md`.
- Durable decisions: `operations/docs/decisions/`.
