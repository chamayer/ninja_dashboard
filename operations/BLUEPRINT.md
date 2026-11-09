# Operations development checkpoint

Plan lifecycle status belongs to the [registry](../docs/records/PLAN_REGISTRY.md).
Earlier mixed implementation notes, evidence, limitations and recovery instructions
are preserved verbatim in the [retained checkpoint](docs/records/OPERATIONS-CHECKPOINT-2026-11-02.md).
That record is historical and must be verified against current files before reuse.

## PLAN-044 — Navigation and Computers performance

**Goal:** Get ordinary Home response time to ≤1.5 seconds (2.0 seconds hard
maximum), preserving the agreed domain-owned overview, supported trends,
Coverage totals, and Clients portfolio boundary. No schema changes.
**Checkpoint:** Reconciled the Home slice on
2026-11-05; preserve PLAN-043 edits in shared files. Patching, Coverage, and
Software current KPIs are present. Home shows total comparisons for Clients and
Inventory; other cards omit trends without a suitable bounded as-of total.
Event-count trend reads were removed. Inventory Home/list totals now use
admitted record subjects, excluding companion observations; records link to
existing first-seen/withdrawal/return history. Patching links to its existing 30-day
install-outcome/activity detail. Software already shows seven-day new-product
and new-high-risk totals plus chronological decision activity. Coverage has
current missing/stale counts and drilldowns but no verdict history. Issues rows
show first-seen, last-detected, and closed timestamps with current status.
Sources already shows recent run outcomes per source; Jobs links to paginated
per-job run histories and result details. Coverage movement review found no
trustworthy Computer-level history; current counts, freshness, and drilldowns
remain the right owner detail. Home now renders meeting/not-meeting Coverage
totals green/red and names the Software risk title count precisely; values still
come from domain owners. Static review found distinct Issues summary and
attention selections; no query consolidation without performance evidence.
`manage.py check`, focused Ruff checks, and 12 Home/navigation tests pass.
`git diff --check` passed. Home skips the unused global client-roster read and
shares one device-status policy read across Computers/Patching summaries.
Home Jobs reads only its health counts and runtime heartbeats. Live measurement
is authorized. One authenticated production Home request returned 200 but
timed out at five seconds before headers. The Inventory owner query was split
into two simpler reads; exact result parity was confirmed on a repeatable
snapshot, 0.80 seconds versus 1.54 seconds combined. This is not a full Home
timing. Local image `manage.py check`, Ruff, and syntax checks pass; focused
pytest is unavailable locally. No migration is pending. **Next:** isolate the
Home changes from PLAN-043, review and push the no-migration change as
authorized, then measure the complete Home response in production. Continue
focused fixes to the ≤1.5-second target (2.0-second maximum). See the
[handoff](docs/plans/PLAN-044-page-performance.md).

## PLAN-015 — Identity reconciliation

Independent of PLAN-043's read-only display work. Registry remains active.
The retained checkpoint reports a validated preview and a guard-aware 110-candidate
follow-up; these historical counts have not been rerun for this task.
**Next:** Verify current state and review candidates before proposing repairs.
Any reattachment, merge or derived refresh needs its own approval.
See the [plan](docs/plans/PLAN-015-identity-reconciliation.md) and retained checkpoint.

## PLAN-016 — Admin SQL explorer

Independent scope; registry remains active with an approval gate. The retained
checkpoint describes planned work; no implementation is claimed here.
**Next:** Obtain implementation approval, then inspect Admin Data routing/tests.
See the [plan](docs/plans/PLAN-016-admin-sql-explorer.md).
