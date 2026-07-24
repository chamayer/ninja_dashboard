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

- [ ] Batch 1 — UI foundation.
  - [ ] `/software/<canonical_name>/` detail view: version breakdown, per-
        device install list, publisher facts, decision history, first/last
        observed, rare/common posture.
  - [ ] Row-level decision actions (Approve / Reject / Investigate /
        Approve Publisher) on the fleet + per-org tables.
  - [ ] Sortable columns on the fleet titles table (device_count,
        client_count, last_install, publisher, canonical_name).
- [ ] Batch 2 — Publisher rollup + admin surface.
  - [ ] `/software/publishers/` list: publisher, distinct titles,
        distinct devices, decision status (approved-publisher / mixed /
        undecided).
  - [ ] `/software/publishers/<publisher>/` detail: titles under this
        publisher with per-title decision state; publisher-level decision
        button.
- [ ] Batch 3 — Whitelist Suggestions.
  - [ ] New FindingType `whitelist_suggestion` (installs ≥ threshold on
        unclassified titles). Threshold in `EvaluatorConfig`.
  - [ ] Findings queue filter chip; drill-through to `/software/<name>/`.
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

- Not yet — batches unstarted.

## Checkpoint

- 0.82.2 (`7708a76`) shipped: patching page perf + grant fix. Software
  track opens here.
- PDQ correction committed alongside the plan: memory
  `project_pdq_never_in_scope.md` filed;
  `operations/docs/legacy-scripts-parity-audit.md` amended in three
  places (analyzer description note, PARTIAL summary, § "Recommended
  sequencing").

## Next action

- Pick Batch 1 (UI foundation) starting scope: title detail page shape —
  columns, sections, drill targets — and align before writing the view.
