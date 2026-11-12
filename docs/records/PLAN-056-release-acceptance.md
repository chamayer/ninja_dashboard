# PLAN-056 — Software release acceptance checkpoint

This release snapshot retains current Software evidence. The original working
acceptance history is preserved in the development workspace; no unrelated Home
candidate or historical diagnostic scripts are part of this release.

## Confirmed local evidence — 2026-11-12

The finite W1–W4 implementation uses existing owner functions and Jobs, including
transactional source/request admission, existing ownership dirtiness, atomic
readiness/Software-owned-assessment/exposure preparation and publication.
Manual finding state is preserved. The
[writer map](PLAN-056-software-writer-coverage.md) records exact coverage/exclusions.

A schema-only isolated synthetic PostgreSQL fixture applied 0407–0410 and used
actual Jobs admission/dependency/dispatch/claim/progress/finish for classifier →
overview, catalog → classifier → overview and empty ownership → overview.
Guarded finding create/resolve, pending/current states, coalescing, successor
preservation, wrong/stale claims, failure retention and retry passed. Failure
after preparation retained previous aggregate/assessment rows and timestamps.
Fixture-only certification switches affected no service data; fixture removed.

Worker execution used a fixture owner role. Intelligence flags were disabled:
matcher/EOL bodies skipped, so populated alias/matcher policy effects and every
admin/association transition were not exhaustively validated. The six previously
recorded Jobs expectation failures remain unresolved; five predate this work.
No test files were changed. Earlier unit/fixture evidence is not representative
freshness or complete security proof.

## Confirmed deployed metadata — 2026-11-12

The approved read-only am-ch-01 preflight found 0406 applied and 0407–0410 absent.
The new overview table/view are absent. Restricted ninja_ingest lacks
finding_types SELECT and exposure-view owner rights. Observed ingest pools
instead use one superuser role with that access; pool metadata does not identify
which connection belongs to the Jobs worker. Source confirms worker/child use
the shared configured login. Existing superuser ingest is a retained platform
security limitation, not a new role-redesign task or a waived contract term.
No grant, migration, producer or service change was made by the preflight.

The reviewed metadata query is retained in
[the preflight SQL](../../scripts/diagnostics/plan056_software_activation_preflight.sql).
It reads no source/customer rows or private configuration.

## Release and remaining acceptance

The [0.144.12 release review](PLAN-056-release-0.144.12.md) owns the isolated
candidate checks, pending migrations, packaging and approval effects.
contract_ready remains false; default Software uses live reads. Products/CSV
remain compatible. A one-off certification flag is not sustained activation
because publication resets it.

Representative compatibility, protected states, <=60-second freshness and full
HTTP <=1.5-second ordinary/<2-second cold proof remain open. Existing superuser
execution cannot establish restricted writer enforcement. Certification and
live-reader cutover require their explicit reviewed disposition. All 15
navigation items remain open. No production speedup or complete contract
acceptance is claimed by this preparation release.
