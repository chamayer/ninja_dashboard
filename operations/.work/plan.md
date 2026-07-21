# Active Operations work plan

Track: **Top Dashboard live implementation**

## Status

- Complete locally — follow-up fixes keep the All clients headers visible and
  repair client-detail queries that still referenced retired Finding/v_device
  columns. A follow-up commit and push remain separately gated.

## Goal

Implement the approved client-first Operations overview with real domain
rollups, plain-language priority, clear data status, and scoped drill-throughs
without regressing tenant boundaries or page performance.

## Scope

- In: Dashboard view queries/context, live Dashboard template, client-side
  session filters/sorting, domain and client drill-throughs, focused tests for
  priority/domain presentation helpers, and local validation.
- Out: database migrations, business-data capture, user/location entity work,
  other page redesigns, commit, push, deployment, and data rebuild.

## Affected files

- `docs/mockups/dashboard-proposal.html` — standalone static mockup.
- `docs/mockups/dashboard-proposal.png` — rendered desktop review image.
- `apps/core/views.py` — efficient fleet/domain/client aggregates and priority.
- `templates/home.html` — approved live Dashboard hierarchy and interactions.
- `apps/core/tests/test_dashboard.py` — focused helper/presentation tests if a
  clean test seam is introduced.
- `operations/.work/plan.md` — active checkpoint.
- `operations/.work/backlog.md` — contains the separately requested deferred
  DMARC integration direction; preserve it.

## Decisions

- The client portfolio is the main section; fleet summaries remain global.
- Portfolio filters/sorts affect only the client list and persist for the
  current session, not indefinitely.
- Client rows show separate domain statuses with a little supporting detail;
  no opaque overall health score.
- Use attention priority for ordering, since almost every client may need some
  attention at different times.
- Retired/inactive entities are secondary context, not primary totals.
- Unavailable Users/business data gets a quiet future-feature teaser rather
  than prominent empty cards.
- Include the optional activity pulse in the mockup so its visual value can be
  judged before deciding whether it belongs in the live page.
- Use operational language instead of data-model language: active devices,
  clients needing attention, all clients, device mix, and plain priority
  labels.
- Keep official module names for navigation familiarity and add a short
  plain-language explanation to each module card.
- Present Integrations as a quieter Data connections status.
- Explain client priority with the leading contributing domain and a count for
  additional domains; reveal all contributors in the client preview.
- Keep locations on the Client page unless a location explains an attention
  item. Keep future user totals separate from device totals.
- Replace the large device-composition and operational-pulse cards with compact
  device-mix and recent-activity lines.
- Use module-aware Data status instead of a misleading single freshness time,
  and distinguish delayed/unavailable data from operational health.
- Make summary counts clear shortcuts into filtered detail. Derive dashboard
  priority from domain conditions; keep acknowledgements and exceptions in the
  module workflows.

## Validation

- Run focused tests for Dashboard helper behavior.
- Run `python manage.py check`, `ruff check`, and `ruff format --check` in the
  documented environment when available.
- Render or smoke-check the authenticated Dashboard against a suitable local or
  explicitly authorized deployed environment; record any unavailable check.
- Review query count/shape and confirm tenant filters and local tenant context
  remain present for raw SQL/effective-view reads.
- Run `git diff --check`.

## Current checkpoint

- Current live scope is 76 clients and 5,167 canonical devices; client users
  are not populated. The mockup may use representative supporting values but
  must label itself as a proposal rather than live data.
- Rendered the standalone page in Edge at 1440 × 1900 and visually reviewed
  the hierarchy, density, domain context, client controls, and optional pulse.
- Confirmed client-domain cells identify the client and destination domain,
  client previews include a clear client-detail action, and list controls use
  browser session storage only.
- `git diff --check` passed (line-ending conversion warnings only).
- No live application files under `apps/`, `config/`, `templates/`, or
  migrations were changed.
- Revised the mockup to use plain operational language, module explanations,
  reasoned client priorities, separate data-delay states, compact device mix,
  and a single-line recent-activity summary.
- Re-rendered at 1440 × 1900 and corrected the module-card footer spacing found
  during visual inspection. The longer labels fit without widening the page or
  obscuring client-domain context.
- Replaced the live issue-centric Dashboard with the approved Operations
  overview: active device/client scope, four domain rollups, client priorities
  with reasons, session-only filters/sort/search, scoped drill-throughs,
  per-client data status, compact recent activity, and future-feature teaser.
- Active/current devices drive primary totals; retired devices remain secondary.
  Priority derives from unsnoozed domain conditions: critical is Act now, high
  is Review next, and medium/low/info is Monitor. Delayed/unavailable data is
  represented separately and cannot appear On track.
- The live view uses fixed-count grouped reads with tenant filters and `SET
  LOCAL operations.tenant_id = 1` around effective-view/raw SQL reads. It does
  not query legacy agent-compliance schemas.
- A proposed Software installation rollup was rejected after a read-only live
  `EXPLAIN ANALYZE` measured 3.8 seconds over roughly 427,000 current rows. The
  implemented card instead uses the small classification catalog plus grouped
  software review/decision counts; full installations remain on Software.
- Read-only live query timings for the implemented expensive shapes were about
  73.5 ms (client/domain issues), 13.7 ms (patch scope), 11.9 ms (device mix),
  41.1 ms (24-hour patch activity), and 4.5 ms (software catalog).
- Validation: `python manage.py check` passed; focused Dashboard tests passed
  10/10; Python compilation passed; the complete template loops rendered from
  synthetic context; changed Python/test files are Ruff-formatted; focused
  Ruff checks passed; `git diff --check` passed.
- Local validation used workstation Python 3.14 rather than the documented
  production Python 3.12. The resulting Django deprecation warnings are from
  that newer interpreter. Full-file Ruff still reports 22 pre-existing issues
  after the changed Dashboard region; the changed region introduces none.
- The initial Dashboard implementation was committed as `46e4335`, pushed to
  deployment authority `origin` and secondary mirror `a-m-rose`, and observed
  running live. No migration or data rebuild was performed.
- Follow-up browser validation confirmed the All clients column headers remain
  sticky while scrolling on desktop; at 1000 px the responsive horizontal
  table remains usable and intentionally uses static headers.
- Live logs identified the Client page 500 as stale schema references in the
  detail query (`Finding.device_id`, `Finding.title`,
  `Finding.first_detected_at`, and `v_device.id`). The local repair uses
  subject identity, JSON finding details, `first_seen_at`, and
  `v_device.device_id` respectively.
- Read-only `EXPLAIN ANALYZE` validation against the deployed database for the
  `am-rose` tenant succeeded for all three repaired query shapes at about 9.6
  ms, 17.9 ms, and 3.5 ms. This was a schema compatibility defect, not missing
  or corrupt `am-rose` data.
- Follow-up local validation passed: Python compilation, `manage.py check`, all
  10 focused Dashboard tests, and `git diff --check`. The Python 3.14-only
  Django deprecation warnings remain unchanged.

## Next action

- Obtain explicit approval for one follow-up commit. After that commit, obtain
  separate approval to push to `origin` and then mirror to `a-m-rose`.
