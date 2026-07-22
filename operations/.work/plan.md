# Active Operations work plan

Track: **Clients directory and client workspace UI**

## Status

- Implementation and local/live read-only validation complete; awaiting visual
  review and refinement. Not committed, pushed, or deployed.
- Separate cross-service observation redesign remains active in the repository
  root plan. Its uncommitted ingest work is out of scope and must be preserved.

## Goal

Turn the Clients area into a human-friendly client directory and make each
client overview a cross-domain workspace rather than a compliance issue list.

## Scope

- **In:** `/orgs/all/`; `/orgs/<client>/` using UTA as the representative;
  compact client navigation; Devices, Inventory, Patching, Compliance,
  Software, and Data Health summaries; clearly identified cross-domain
  attention; client context; visible empty/unavailable states; live-render
  performance; the exposed base-template comment defect.
- **Out:** ownership/assignment (backlog); full history implementation;
  location/user detail pages; new schema or migrations; Admin workflow
  implementation; commit, push, and deployment.

## Affected files

- `apps/core/views.py`
- `templates/base.html`
- `templates/org_index.html`
- `apps/core/tests/test_client_workspace.py` (new, if focused helpers warrant it)
- `.work/backlog.md` (ownership/assignment follow-up only)

## Decisions

- Never hide a domain; distinguish operating normally, needs attention,
  unconfigured, delayed, and unavailable.
- Do not calculate one overall client health label. Summarize how many areas
  need attention and retain separate domain states.
- Domain panels precede the combined attention list. Attention rows identify
  their domain and link to filtered workflows.
- Client configuration lives under Admin; the overview is read-only context.
- Preserve client scope and breadcrumbs on every drill-through.
- Filters, sorting, and return state are session-scoped. Ownership/assignment
  is deferred.
- Inventory is foundational visibility; corrective identity work is Admin.

## Steps

- [x] Review current deployed Clients and UTA pages against legacy questions.
- [x] Measure deployed server rendering and isolate the dominant query cost.
- [x] Build the richer fleet directory and UTA cross-domain overview.
- [x] Fix compact client navigation and the visible template comment.
- [x] Avoid per-request full software anti-join scans in summary metrics.
- [x] Add focused tests for derived presentation state where practical.
- [x] Run Django checks, Ruff, targeted tests, template/request smoke checks,
  and `git diff --check` in the documented environment.
- [x] Render privacy-safe representative screenshots and review visually.

## Validation plan

- `python manage.py check`
- `ruff check` and `ruff format --check` for changed Python/tests
- Targeted pytest
- Tenant-scoped render smoke checks for `/orgs/all/` and `/orgs/uta/`
- Compare UTA server render/query timing with the measured 2.6-3.8 seconds and
  26 queries; two software queries previously consumed about 1.9 seconds.
- `git diff --check`

## Checkpoint

- Current live UI reviewed. `/orgs/all/` is a narrow three-column duplicate;
  UTA is compliance-triage-heavy and exposes technical configuration.
- Live UTA render measured at 2.554-3.836 seconds. Query capture attributed
  1.879 seconds to two software queries, including a 1.733-second pending-title
  anti-join.
- `templates/base.html` uses a multiline `{# ... #}` comment that renders as
  visible text and expands the navigation bar.
- Unrelated uncommitted `../ingest/identity/resolver.py` work belongs to the
  root observation redesign and was untouched. The shared branch advanced to
  `095304c` through cross-service commits while this slice was in progress;
  this UI work was reconciled afterward and has no overlapping files.
- First visual now uses a compact context strip, six always-visible domain
  panels, a domain-labelled attention table with session-persistent controls,
  recent-change preview, and read-only Admin pointer. The fleet page is a
  broader sortable/filterable client directory rather than an issue-priority
  duplicate of Dashboard.
- The multiline base-template comment is converted to a real Django comment;
  the client nav is Overview, Devices, Patching, Software, Issues, and More.
- Validation: `python manage.py check`; both templates load; Ruff check and
  format-check pass for new Python/tests; import checks pass for the narrow
  `views.py` edit; 18 targeted tests pass; `git diff --check` passes.
- Read-only UTA timing against deployed data: existing context 0.568 seconds;
  added workspace aggregation 0.236 seconds / 11 queries / 0.032 database
  seconds. Fleet directory addition: 0.287 seconds / 8 queries / 0.092 database
  seconds for 76 clients. No deployment timing is claimed yet.
- Privacy-safe UTA and fleet screenshots were rendered at 1440px and reviewed.

## Next action

- Present the visual and validation result for user review. Refine the visual
  if requested; seek separate approval before commit, push, or deployment.

## Cross-service pointer

The observation redesign authority remains the repository-root `.work/plan.md`
and `docs/decisions/0007-observation-model-content-hashed-current-plus-history.md`.
This Operations UI plan does not modify or supersede that track.
