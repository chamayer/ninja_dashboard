# PLAN-045 — emergency ownership backlog repair

## Goal and authorization

User authorized committing and pushing the emergency repair through completion.
Normal operations were restarted after the 0.144.3 deadlock repair. Production
source runs recovered, but ownership dirty rows remained older than 30 minutes.

## Confirmed state

The remaining backlog was traced to the resolver doing a full-fleet ownership
sweep before identity matching, then draining dirty ownership after matching.
The resolver also runs client resolution, promotion, merging, cache and layer
projection, and naming. A prior production check showed 10 dirty ownership
rows, 9 older than 30 minutes, while the resolver had run for about 40 minutes.
Refresh live state before reporting current counts.

## Scope and design

Keep identity association and promotion in the resolver. Move source-derived
Computer ownership reconciliation into coalesced dirty-only Jobs triggered
after source writes and resolver completion. Move full-fleet ownership repair
to its own daily, low-priority maintenance Job. Keep database serialization at
the existing tenant guard, but hold it for only one Computer projection per
transaction. This bounds how long an ownership projection can block other
tenant writes while preserving the findings lock order and atomic update of a
Computer and its dependent scope rows. Avoid a whole-job identity lock, new
queue framework, or database migration.

## Current work — bound guard duration

Production after 0.144.6 showed the split workflow succeeds, but projecting a
set of dirty Computers in one transaction can hold the exclusive findings
guard for minutes. Project each Computer in its own guarded transaction so
other writers can proceed between Computers. A failure leaves remaining rows
dirty for the next run; each Computer's ownership and dependent rows remain
atomic.

After 0.144.7 deployed, production exposed another long guard holder:
`platform-health-evaluate` performs one `admin_findings` scan per unmet Jobs
dependency. Read-only inspection found 330 unmet dependencies, 5,718 stored
dependency rows, and three waiting exclusive-guard writers while that evaluator
held the guard for about 2.5 minutes. Load active Jobs failure findings once
and resolve dependency parents from that in-memory set. Preserve the current
priority (timeout, repeated failure, then schedule failure) and latest-finding
selection. Do not alter the shared guard contract.

Affected files: `ingest/identity/computer_client_ownership.py`,
`ingest/platform_findings.py`, focused tests, `VERSION`, `CHANGELOG.md`, this
checkpoint, and the PLAN-045 registry entry. No SQL migration is expected.
Validate focused ownership and platform-finding tests, registry validation,
syntax, Ruff, and `git diff --check`; then verify live guard waits and dirty age
after the authorized release.

## Prior validation and current next action

The split is implemented: identity resolution no longer runs ownership sweeps;
source refresh and agent observations request coalesced dirty-only work, and
resolver-created dirties are caught by a 10-minute dirty-only schedule. A
separate daily low-priority full sweep is registered. Production 0.144.5 is
healthy; one ownership run completed with 12 resolved, 1 conflict, and 3
unknown rows, leaving 0 live dirty rows. AMROSE ScreenConnect completed after
writing 5,617 records without a deadlock. Its successor exposed that coalesced
Jobs dependencies made source-triggered ownership wait for the resolver too;
0.144.6 removes that prerequisite and adds the catch-up schedule. All ten
focused resolver/ownership tests pass; registry smoke, plan registry,
compileall, Ruff, and diff checks pass. Workflow-admission tests could not
collect because the local Python environment lacks `pydantic`; no dependencies
were installed. No migration or full-fleet local run was added. The first
0.144.4 rollout exposed that
replay-safe Jobs policies require per-definition database authority rows; the
worker stayed down until this was corrected by keeping these jobs in manual-
review recovery mode, without adding a migration. Version 0.144.5 contains the
correction. Version 0.144.6 is deployed. Production confirmed a ScreenConnect
source run's ownership child depended only on source refresh, completed with 21
resolved while the resolver was still running, left 0 dirty rows (0 older than
30 minutes), and logged no deadlocks in the worker's preceding 30 minutes.
Version 0.144.7 is deployed; the Jobs worker and ingest recovered healthy after
the automatic rollout. Current next action: validate the bulk lookup, release
0.144.8, then verify production guard waits and source recovery.
