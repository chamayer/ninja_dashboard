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
resolver completion requests it for newly associated Computers. A separate
daily low-priority sweep is registered. All nine focused resolver/ownership
tests pass; registry smoke, plan registry, compileall, Ruff, and diff checks
pass. Workflow-admission tests could not collect because the local Python
environment lacks `pydantic`; no dependencies were installed. No migration or
full-fleet local run was added. Next commit and push the reviewed 0.144.4
release, then verify deployment, dirty ownership age, and source runs.
