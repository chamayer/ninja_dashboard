# Active root work plan

Track: **Collection-complete derived refresh**

## Status

- Complete locally and verified live — collection-complete refresh works, and
  the follow-up removes the duplicate resolver refresh. Follow-up commit and
  push remain separately gated.

## Goal

Ensure every source collection path refreshes the Operations derived state it
feeds before reporting completion, so freshness and workflow surfaces cannot
lag behind successfully collected data.

## Scope

- In: shared Operations derived-refresh helper; scheduled Ninja and agent
  observation cycles; on-demand Ninja and individual-source queue runs;
  focused validation; durable architecture decision.
- Out: collection cadence changes, database migrations, source credentials,
  legacy-schema behavior, manual production refresh, commit, push, and deploy.

## Affected files

- `ingest/derived.py` — one shared post-collection refresh boundary.
- `ingest/main.py` — scheduled/startup and on-demand Ninja call sites.
- `ingest/source_run_queue.py` — on-demand individual-source completion.
- `ingest/identity/resolver.py` — skip its narrower refresh only when the
  caller immediately runs the full coordinator.
- `docs/architecture.md` — explicit collection-completion invariant.
- `docs/decisions/0004-refresh-derived-state-after-collection.md` — durable
  decision and failure semantics.
- `.work/plan.md` — active root checkpoint.

## Steps

- [x] Confirm the dashboard timestamp is stale derived state, not stale raw
  collection data.
- [x] Inventory scheduled and on-demand source collection boundaries.
- [x] Implement one shared refresh helper and wire every boundary.
- [x] Add focused regression coverage where the current test environment
  permits it.
- [x] Run proportional syntax, lint, diff, and live read-only validation.

## Decisions

- A source collection is not complete until its dependent current/derived
  state has refreshed.
- Apply the same completion rule to scheduled, startup, and on-demand runs.
- Keep source collection records and refresh failures distinguishable; a
  refresh failure must be surfaced and must not be logged as successful queue
  completion.
- Software collection already refreshes
  `software_installations_current` internally and is not duplicated here.

## Validation plan

- Parse/compile changed ingest modules.
- Exercise the helper and each call boundary with mocks if imports permit.
- Review that failed refreshes propagate to on-demand queue failure handling.
- Run focused Ruff checks and `git diff --check`.
- Validate raw source timestamps versus `source_health_current` read-only;
  production mutation/deployment requires separate approval.

## Current checkpoint

- Raw live source data is current: non-Ninja observations completed at 11:45
  AM EDT and Ninja completed at 2:46 PM EDT on 2026-07-21.
- `operations.source_health_current` was last computed at 10:08 AM EDT, so the
  Dashboard incorrectly continued to show that older timestamp.
- `run_agent_observations_once()` and individual-source demand runs collect and
  resolve observations without a final `operations.refresh_derived()` call.
  Ninja refreshes some dependent views inside device ingest but also lacks the
  common completion boundary.
- Added `refresh_after_collection()`, which calls the existing coordinator and
  intentionally propagates errors. Scheduled patch/Ninja, scheduled/startup
  agent observations, on-demand Ninja, and on-demand individual-source paths
  now use it before logging or recording successful completion.
- Software's scoped collector already calls
  `operations.refresh_software_installations_current(1)` after writes, so no
  duplicate shared refresh was added to that domain path.
- Local validation passed AST parsing, a mocked successful coordinator call,
  refresh-exception propagation, static coverage of all four boundaries,
  focused fatal Ruff checks, the new helper's Ruff format check, and
  `git diff --check`. Full-file import sorting remains pre-existing drift in
  `ingest/main.py` and a late-import block in `source_run_queue.py`.
- Read-only live validation confirmed `ninja_ingest` has execute privilege on
  `operations.refresh_derived()` and the function is owned by
  `operations_migrate`.
- Deployed commit `dca4855` completed startup collection successfully. Raw and
  derived observation timestamps both advanced to 3:29 PM EDT; the explicit
  refresh completed at 3:31:59 PM and only then did the collection log
  completion. The run also revealed duplicate presence/session refreshes in
  the resolver immediately before the full coordinator.
- The follow-up passes `refresh_current=False` only when scheduled/startup or
  on-demand source collection immediately invokes the full coordinator.
  Standalone resolver calls retain the default `True` behavior. AST contract
  checks, focused fatal Ruff checks, and `git diff --check` passed.

## Next action

- Obtain approval for the narrow performance follow-up commit, then separate
  push approval and one final deployed collection timing check.
