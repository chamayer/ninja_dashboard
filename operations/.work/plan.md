# Active Operations work plan

Track: **Software dashboard + classification engine + legacy-analyzer parity**

## Status

- Scoping — reconciliation complete, sequencing agreed, no implementation
  started.

## Goal

Turn `/software/` from a fleet-summary page into a real dashboard with
summary → detail drill-through, and close the outstanding parity gaps
against the legacy `analyze_inventory.py` (Ninja-CSV-based, 3041 lines).
Reconciled against 0.82.2; earlier "PDQ" references in the parity audit
were a misreading and have been struck.

## Scope

- `apps/core/views.py::software_page` and new per-title / per-publisher
  detail views.
- `apps/core/models.py::SoftwareClassifierRule`, `SoftwareCatalog`,
  `SoftwareDecision`.
- `templates/software_*.html` — new detail templates + row-action fragments.
- New Whitelist Suggestions finding / queue.
- Wire `Device.last_user` → `ClientUser` for installs × user correlation.
- CVE enrichment enters via a separate ADR and stays behind a feature flag.
- **Not in scope:** Excel/VBA output; PDQ ingestion (never was a source).

## Decisions

- **Data source parity is already achieved.** `ingest/inventory/software.py`
  ingests the same data the legacy Ninja CSV exports carried. No new
  connector needed for parity.
- **Classification stays split.** `SoftwareClassifierRule` produces evidence
  (SUSPICIOUS_NAME, INSTALL_PATH_SUSPICIOUS, EOL_RUNTIME); `SoftwareDecision`
  produces trust (APPROVE, APPROVE_PUBLISHER, REJECT, INVESTIGATE). The
  legacy WHITELIST and TRUSTED_PUBLISHERS live as decisions, not rules.
  Unifying them is deferred until an operator hits an actual limitation.
- **Categories stay data-driven.** `SoftwareCatalog.categories` (jsonb) is
  the admin-maintainable taxonomy per the "mappings live in data" rule.
  No hardcoded category enum.
- **User-risk unblocked.** `ClientUser` + `ClientUserLink` shipped;
  `ingest/core/devices.py:129` writes `last_user`. Only the install ↔ user
  join is missing.
- **CVE is external and gets its own ADR.** Introduces a new data source,
  rate limits, secret handling; not bundled with UI work.

## Verified gap list (audit 0.69.0 → reconciled at 0.82.2)

| Gap area | State @ 0.82.2 | Verdict |
|---|---|---|
| CVE / vulnerability enrichment | No CVE tables/models, no NVD code | Open |
| User-risk (software × user) | `ClientUser`/`ClientUserLink` shipped, `last_user` ingested, join missing | Partial |
| Publisher rollups + publisher-level decisions | `APPROVE_PUBLISHER` decision exists; publisher is filter facet + column; no rollup / detail view | Partial |
| Tech Checklist | Nothing | Open |
| Whitelist Suggestions queue (installs ≥ N unclassified) | Rare-side (`rare_recent`) shipped; common-unclassified side missing | Open |
| Per-title detail page + row actions + sortable columns | Nothing (fleet page is summary-only) | Open |
| Excel/VBA output | Deliberate out-of-scope | Not doing |
| ~~PDQ ingestion~~ | ~~n/a~~ | Struck — misreading |

## Steps

- [x] Batch 1 — UI foundation (0.83.0).
  - [x] `/software/title/<name>/` detail view.
  - [x] Row-level decision actions on the fleet + per-org tables (per-org
        already shipped; fleet added; both link to the new detail page).
  - [x] Sortable columns — already provided by the universal `data-sortable`
        JS in `base.html`, no per-page work needed.
  - [x] Functional index (migration 0078) so case-insensitive canonical
        lookups don't seq-scan software_installations_current.
- [x] Batch 2 — Publisher rollup + admin surface (0.84.0).
  - [x] Migration 0079: adds `publisher` to `SoftwareDecision`, makes
        `canonical_name` blank-able, XOR check constraint enforcing
        exactly one of the two, six partial unique constraints.
  - [x] `_load_decisions` / `_resolve_decision` in
        `ingest/software_findings.py` now honour publisher-scope tiers
        (title-scope wins; publisher-scope is fallback).
  - [x] `/software/publishers/` list + `/software/publishers/<pub>/`
        detail with row-level publisher-scope decisions and title
        clickthrough.
  - [x] `software_decision_create` accepts `publisher` and enforces the
        XOR at the form level.
  - [x] Fleet page `?decision=` filter now considers publisher-scope
        approvals/rejections/pending.
  - [x] Nav: fleet page has a Publishers tile; per-title publisher list
        links to publisher detail; per-publisher title list links to
        title detail.
- [x] Batch 3 — Whitelist Suggestions (0.85.0).
  - [x] New `whitelist_suggestion` FindingType (migration 0080), seeded
        via `get_or_create` under the software category with
        `source_module='platform.software_findings'`.
  - [x] Classifier step 7 emits it for uncategorised + undecided +
        fleet_device_count ≥ threshold. Threshold + severity + enabled
        knobs on the software_classifier `EvaluatorConfig`
        (`whitelist_suggestion_min_devices` default 10, `_severity`
        default low, `_enabled` default true).
  - [x] Separate tile on `/software/` (deduped by canonical_name) —
        distinct from the "flagged installations" tile so suggestions
        don't inflate the problem count.
- [ ] Batch 4 — Tech Checklist.
  - [ ] Per-device curated cleanup list (rejected + investigate +
        suspicious-rule matches on the device's install set) as an
        Operations report / view.
- [ ] Batch 5 — User-risk join.
  - [ ] Correlate `Device.last_user` (or the merged ClientUser link) with
        `software_installations_current` and surface a per-user risk view.
- [ ] Batch 6 — CVE enrichment (own ADR).

## Validation plan

- Per-batch: `python manage.py check`, template loading, targeted tests,
  ruff, `git diff --check`.
- Deployed-DB read-only smoke check per batch via the workspace helper.
- Every new query that scans a large table gets an `EXPLAIN` before push.
- Every new DB object (table, view, matview, finding_type row) gets its
  grants matched against sibling objects before push
  (`feedback_no_careless_mistakes` rule 8).

## Validation

- Batch 1 (0.83.0):
  - `python -m compileall` on changed views/urls — pass.
  - `python manage.py check` — pass.
  - `python manage.py sqlmigrate operations 0078` — renders cleanly.
  - `python manage.py makemigrations --check --dry-run` — no changes.
  - Template loading (`software_page`, `software_detail`, `org_software`,
    `software_decisions`) — pass.
  - `pytest apps/core/tests -q` — 23 passed.
  - Deployed-DB dry-run (transaction + `ROLLBACK`): Google Chrome install
    list 588 ms → 112 ms after functional index.

## Checkpoint

- Batch 1 shipped as 0.83.0. Software fleet page has row-level decisions
  and a working title detail drill-through; case-insensitive canonical
  lookups are index-backed.
- Next batches unstarted: publisher rollup, Whitelist Suggestions,
  Tech Checklist, user-risk, CVE.

## Next action

- Open Batch 4 — Tech Checklist. Per-device curated cleanup list:
  reject/investigate decisions + suspicious-rule matches present on the
  device's current install set, surfaced as an Operations report.
