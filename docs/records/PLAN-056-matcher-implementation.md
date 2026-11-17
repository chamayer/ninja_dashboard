# PLAN-056 — CVE matcher difference persistence

## Scope and authority — 2026-11-11

The user approved this third implementation slice and focused tests. HEAD remains
`ca00938a`; Coverage, relationship guard and earlier unrelated working changes
are preserved. Changes are `ingest/intel/matcher.py`, the existing candidate-cache
test adapter and a new focused PostgreSQL test module. No migration, dependency,
public-interface or configuration change. Release, commit, push and external
validation retain separate gates.

## Implementation and review

Full candidate/version evaluation now emits into `pg_temp.cve_match_desired`.
The stage has the same five-column NULLS NOT DISTINCT key as migration 077.
Only after matching completes does publication delete absent keys and insert or
update different content. Both version-range and confidence comparisons are
null-safe. Equal desired rows are filtered before upsert, avoiding conflict locks
and sequence allocations for the equal population. Surviving IDs are stable;
equal rows also retain physical tuple identity and `matched_at`. Content changes
advance `matched_at`. This compatibility decision is
[ADR-0057](../../operations/docs/decisions/0057-cve-match-difference-publication.md).

The existing before snapshot, six-field material comparison, audit function and
generation-aware reclassification targets are retained. Empty installed scope,
empty CPE input and zero matches now use the same publication/audit/target path;
the former early return deleted rows without recording removal history/targets.
Repeated empty results produce no further audit or target generation changes.
Safety refresh remains unconditional in `run_once`; matching count and
`MaterialCount.material_changed` interfaces remain intact.

Reviewed ID/timestamp consumers, SQL migrations 072/077, migration 0306's writer
audit and the 0250/0277/0349 target contracts. No repository runtime consumer of
match row IDs or `matched_at` freshness was found. Persistent history and target
publication stay in the same transaction as match changes; existing optional
table probes remain for startup compatibility. Both temporary tables drop on
transaction completion. The existing ingest Dockerfile includes the runtime
file with `COPY ingest/ ./ingest/`; no packaging/Compose change is needed.

## Actual validation

- **24 focused matcher checks pass:** 16 existing candidate-cache/CPE-index
  checks and eight new persistence/refresh cases. Existing mocked cursor tests
  were adapted to the staging boundary; PostgreSQL checks verify actual DML.
- Seven new PostgreSQL cases use one disposable PostgreSQL 16 container,
  synthetic input tables and the real migration 0306 audit foundation plus
  0250/0277/0349 target SQL. Matcher transactions execute as `ninja_ingest`, with
  forced tenant RLS on match rows and migration-defined target policies.
- Cases verify version-specific and NULL-version keys, repeat equality with no
  physical-row/ID/timestamp/sequence/history/target changes, additions/removals,
  separate confidence and nullable range changes, all three empty-input forms,
  other-tenant preservation and a target constraint failure after audit has run.
  That failure rolls back matches, audit and targets together; a retry succeeds.
- The eighth new check confirms `run_once` refreshes safety when match membership
  is unchanged. No real materialized view or production scoring pass runs.
- **Four existing matcher target-generation concurrency checks pass** (six
  unrelated parameter cases deselected). No generation SQL changed.
- Compilation and Ruff lint pass for all three Python files. The new test module
  passes Ruff formatting. Final registry/whitespace/link/handoff checks are in
  the active blueprint. Testcontainer cleanup leaves preexisting dev services.

## Limits and next action

The fixture does not install the complete application schema or all production
constraints. No fleet run, local timing benchmark, live query or performance
claim. Full candidate computation, snapshot and temporary desired-table/index
work remain; savings in production write volume and platform latency are
unmeasured. No version/changelog update is made before an approved release.

Review this logical change separately from the other uncommitted fixes. Before
commit/push, review exact selected contents and pending migrations. External
acceptance needs a bounded protocol and approval. PLAN-056 remains active and
resource interaction remains deferred. Reversion scope is matcher persistence
and its test adapter; never revert the preserved unrelated work wholesale.
