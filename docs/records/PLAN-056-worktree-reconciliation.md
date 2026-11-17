# PLAN-056 — Worktree reconciliation and release

## Status and scope

Release prepared, 2026-11-17. User authorized reconciling all working changes and
deploying the result; requested light tests. This supersedes the earlier
Home-only release boundary. PLAN-056 remains active; navigation acceptance and
domain-reader follow-ups are not closed by deployment.

## Decisions and steps

1. Inventory tracked/untracked work and preserve relevant diagnostics/evidence.
2. Retain the final cheap-count Home route and client-evidence optimization.
   Retire the conflicting Home cache/legacy dashboard candidate and unused live
   Software Home helper; reconcile their existing tests with the final content.
3. Retain global/domain read-contract documentation, performance evidence and
   plan/backlog routing. Historical evidence remains historical, not a current
   production claim. Review diagnostics for secrets/customer literals and unsafe
   automatic execution; keep manual diagnostics outside runtime packaging.
4. Reconcile line-ending-only migration/test changes without changing semantics.
5. Prepare VERSION/CHANGELOG together; run focused checks, migration comparison,
   packaging and whitespace review; commit logical changes, origin then mirror.
6. Observe automatic deployment, service health, release identity and one
   authenticated complete Home request with normal logout. No manual redeploy.

## Migration and release boundary

Read-only production preflight: all Operations migrations through 0417 are
applied, including 0406. Ingest latest is 119_patch_outcome_counts, matching the
local migration sequence. No pending migration or new schema change identified.
0406 and its test file have no content diff after ignoring line endings.
Both remotes currently point to eab79e1d. No credentials/private settings were read.

## Validation and checkpoint

Reconciled Home, mapping-workflow and table/template checks: 26 passed before
the user explicitly stopped further testing. No more tests were run afterward.
Source review/audit found no private-key or credential-literal matches in the
retained untracked source; historical mutating diagnostics are manual-only,
outside runtime packaging. Eight root probes were archived, not discarded.
Retired the cache/legacy dashboard and unused live Software Home helper; retained
the client-evidence optimization. Updated existing Home tests and obsolete
template expectations. Cosmetic 0406/test line endings introduce no migration.

Release 0.144.23 prepared with VERSION/CHANGELOG. User authorized commit and both
pushes with automatic deployment. Migration preflight found none pending. Next:
push origin then mirror and observe automatic deployment only; no more testing.
