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
the existing bounded tenant transaction guard; avoid a whole-job identity lock,
new queue framework, or database migration.

## Validation and next action

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
correction. Next release 0.144.6 and verify source-triggered ownership runs do
not wait for identity resolution, while normal source collection remains clear.
