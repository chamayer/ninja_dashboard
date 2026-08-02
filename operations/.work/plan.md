# Active Operations implementation plan

Track: **Corrective Track B — stable observation identity review**

**Status:** RELEASE CANDIDATE AWAITING PRODUCTION MIGRATION APPROVAL —
stronger-model review, aggregate-only production measurement, additive
implementation, and local validation passed. Release `0.99.0` is being
committed under the existing authorization but is not deployed.

## Goal

Turn accepted ADR-0009 into a verified, implementation-ready expand/backfill
slice without changing the deployed ADR-0007 identity authority yet.

## Scope

- Reconcile ADR-0009 and the root DB2 inventory with current code and schema.
- Measure aggregate binding topology, source/type populations, parent-scoped
  identities, and duplicate-active risk without exposing customer data.
- Write and review a deterministic namespace/backfill rule for every current
  source-record family.
- Recommend the first additive migration slice, its rollback boundary, and the
  next approval gate.

Out of scope: schema changes, migrations, backfill execution, dual writes,
consumer cutover, contract cleanup, Agent Compliance changes, and the wider
ADR-0010 entity/claim/admin implementation.

## Design authorities

- ADR-0007 v5 remains authoritative for deployed behavior.
- Accepted ADR-0009 governs the target stable identity and reconciliation.
- Accepted ADR-0010 constrains compatibility with the later generic source
  record contract but is not implemented in this phase.

## Affected surfaces to verify

- Observation models, current/history uniqueness, snapshot-run models, RLS,
  retention, and seed/maintenance commands.
- `ingest/observations.py`, `ingest/observation_runs.py`, all current writers,
  identity/client resolvers, evaluator readers, dependent views/matviews, and
  Operations read/write workflows.
- Source/instance/binding seeds and connector external-ID semantics.

## Steps

1. **Complete:** reconciled the checkpoint with Git at `0c90b14`, confirmed
   both remotes match, and reread the current instructions and ADRs.
2. **Complete:** revalidated the affected surfaces and derived deterministic
   namespace/parent-scope rules from connector-owned external IDs.
3. **Complete:** measured binding topology, current/history populations,
   parent scope, integrity, and proposed-key collision risk.
4. **Complete:** all deployed rows map; no proposed current/open-history
   collision or unresolved parent scope exists. ScreenConnect's synthetic
   container uses stable identity `(source-instance, self)` rather than its
   editable legacy label.
5. **Complete:** implemented and locally validated additive migration `0095`;
   ADR-0007 writes/readers remain authoritative.
6. **In progress:** prepare the authorized release commit, then obtain explicit
   approval for the `origin` push, automatic deployment, and startup execution
   of migration `0095`, followed by the secondary-mirror push and aggregate
   verification.

## Validation plan

- Repository-wide reference inventory and migration/model comparison.
- Aggregate-only production SQL through the documented helper; no raw payload,
  identifier, hostname, client, or customer record output.
- Cross-check totals and collision counts under both deployed and proposed
  identity tuples.
- Review the recommended expand/backfill design for RLS, uniqueness,
  concurrency, rollback, and named consumer compatibility.

## Checkpoint

Track A and the resolver correctness repair are complete and deployed through
`0.98.8` / `0c90b14`. Existing unrelated dirty plans, docs, backlog work,
probes, and untracked accepted ADR drafts are preserved. Track B review is now
active under the user's autonomous continuation authorization. The current
model is appropriate for the identity-migration review.

Aggregate production measurements (2026-08-02): each of Ninja, SentinelOne,
ScreenConnect, LogMeIn, and Hudu has 1 source instance and 1 enabled binding;
no instance has multiple bindings. Current has 24,284 rows (23,895 active),
history has 38,879 rows (23,895 open), and snapshot runs has 607 complete rows.
All external IDs are non-empty, all parent scopes are empty, and all bindings
resolve to a source instance. Proposed stable namespaces cover every row and
produce 0 current collisions, 0 open-history collisions, and 0 historical
cross-type identity groups. Legacy current/open-history accounting has 0
active-without-open, 0 inactive-with-open, and 0 open-without-current rows.
The synthetic ScreenConnect container has 1 legacy key across 3 history rows
and 1 open row, so normalizing it to external ID `self` is collision-free.

Implementation adds nullable/empty shadow identity and transport-provenance
fields to current/history plus source-instance, run-start, and explicit
completeness fields to snapshot runs. It backfills only those new fields;
legacy columns, constraints, readers, writers, current/history rows, and
canonical attachments remain unchanged. Current writers omit the new fields,
so existing-row updates preserve their backfill and any newly learned identity
remains safely legacy-authoritative with an empty shadow until the separately
reviewed dual-write slice.

Validation: the focused backfill test passes against PostgreSQL 16 for every
current source family; migration `0095` applies, reverses, and reapplies on a
disposable PostgreSQL migration graph; its three sample backfills each matched
the expected values. All 26 other Operations tests pass (the opt-in PostgreSQL
test is the only default skip), Django reports no model-state changes and no
system-check issues, changed-file Ruff and formatting checks pass, Python
compilation and `git diff --check` pass. The Operations image build is locally
blocked before application packaging by Docker's PyPI certificate-chain
failure; no code-layer build failure occurred. Production preflight confirms
the three tables are owned by `operations_migrate`, no shadow columns exist,
the latest migration is `0094`, and measured row counts remain 24,284 current,
38,879 history, and 607 runs.

## Next action

Commit the authorized `0.99.0` release candidate. Then obtain explicit approval
for the `origin` push including automatic deployment and startup execution of
migration `0095`; if approved, deploy, measure backfill coverage,
collisions/health/500s, then push the mirror.
