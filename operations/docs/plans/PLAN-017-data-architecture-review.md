# PLAN-017 — Data and technical architecture review

## Goal

Validate the data and technical architecture, from ingest through page
reads, against three criteria:

1. **Performance** — collection writes, refreshes, projections, evaluation,
   and page reads scale with the fleet without avoidable cost.
2. **Data integrity** — every stored fact is correct, consistent with its
   authority, enforced by a mechanism, and stays correct under retries,
   partial collections, concurrency, and refresh ordering.
3. **No unnecessary duplication** — each fact has one authority; every copy
   is a declared derivation with a known refresh path; no logic or
   definition is re-implemented; no store is written but never read.

The output is a graded findings register, not fixes. Each finding is routed
to an existing plan, a new separately approved plan, or an explicit
acceptance.

## Why now

The 2026-10-23 Computer pipeline review (PLAN-012 completion gate) found
re-derived requirement policy, several definitions of "active", a
projection labelled "shadow" that feeds every consumer, apparently unread
stores, and a 4.9-second source-record read with suspected storage churn.
These are likely present in other domains.

## Coverage

Every store and pipeline stage, examined only through the three criteria:
source observations and source-branded staging (`ninja_core`,
`ninja_patches`, `agent_compliance`); client and Computer identity; attribute
claims, effective values, typed caches, and facet tables; materialized views
and refresh functions; software, patching, activity, Hudu, and reference
(intel) stores; requirement verdicts, findings, and conditions; operator
decisions; job and run state; and the page/CSV readers that consume them.

Out of scope: access control beyond tenant-integrity, sensitive-data
handling, backups, outbound integrations, UX, and implementing any fix,
schema change, data change, retirement, or deployment.

## Workstreams

### A. Duplication

1. **Store inventory** — every table, view, materialized view, and function
   (migrations plus ingest SQL, reconciled to the live catalogue): grain,
   layer, writer(s), readers.
2. **Authority map** — for each operator-relevant fact (identity keys, client,
   OS, role, type, online, contact, lifecycle, requirement verdict, patch
   state, installation), its single authority and every copy with derivation
   and refresh path.
3. **Parallel paths** — stores or pipelines that hold the same facts (for
   example `ninja_core` beside observations, facet tables beside Device
   caches, legacy agent-compliance beside native coverage).
4. **Re-implemented logic** — rules and definitions computed in more than one
   place (thresholds, applicability, current-Computer population, contact),
   and values hard-coded in code or SQL that duplicate registry or
   configuration data (for example tenant `1`, the Ninja source-instance ID,
   source URLs).
5. **Unread or unwritten stores** — candidates for retirement, with reader
   evidence including SQL views and Metabase.

### B. Data integrity

1. **Constraints versus invariants** — each documented rule (DESIGN.md,
   `architecture.md`, glossary, ADRs) checked for an enforcing constraint,
   privilege, trigger, or test.
2. **Referential and scope integrity** — orphans, cross-tenant or cross-client
   references, unscoped records referencing scoped ones.
3. **Ingest contracts** — completeness, withdrawal, out-of-order and
   idempotency guards per connector, and the checks that stop a failed or
   partial run from withdrawing records or aging Computers.
4. **Time semantics** — source time versus collection time, timestamps
   stored without a time zone, and consistent use of each across readers.
5. **Value validity** — well-formed and consistently normalized values
   (hostnames, serials, identifiers, enumerations) and consistent meaning of
   NULL versus unknown versus absent.
6. **Refresh ordering** — collection → resolution → projection → refresh →
   evaluation; where readers can combine different refresh generations.
7. **Concurrency** — overlapping writers (collectors, resolver, evaluator,
   operator actions) and their locking.
8. **Copy drift** — measured disagreement between each derived copy and its
   authority (read-only counts).

### C. Performance

1. **Storage health** — table, TOAST, and index sizes; dead tuples; HOT ratio;
   index use (unused and missing); history and staging growth, and whether
   each history or staging store has an enforced retention policy.
2. **Write cost** — per-collection rows rewritten, index maintenance, and
   write amplification of each writer.
3. **Refresh and projection cost** — materialized-view and projector
   runtimes, wholesale versus incremental refresh.
4. **Read paths** — `EXPLAIN (ANALYZE, BUFFERS)` of the main page, card,
   drill-through, and CSV queries; unbounded reads; repeated scans per load.
5. **Job runtimes** — duration and load of collection, resolution, and
   evaluation cycles.
6. **Application-side cost** — Django-side query counts (N+1 patterns),
   whole-result materialization in Python, rendering of unbounded result
   sets, and missing pagination on page and CSV paths.

## Evidence standard

Each finding is graded **Confirmed** (exact code reference, or a measured
result with unambiguous interpretation), **Suspected** (consistent with
evidence, named diagnostic pending), or **Unverified**. Measurements are
stated as measured: `BUFFERS` counts block accesses, not unique pages; heap
fetches are visibility checks, not dead-tuple counts.

## Deliverables

`docs/records/DATA_ARCHITECTURE_REVIEW-<date>.md` containing the findings
register (ID, criterion, statement, grade, evidence, impact, routing), the
store inventory, the authority map, and the refresh-order graph (stage,
trigger, inputs, outputs, failure behavior).

## Phases and gates

| Phase | Work | Gate |
|---|---|---|
| 0 | Confirm charter | User approval to start |
| 1 | Static review: A1–A5, B1–B7, C2–C3, C6 from code and migrations | None beyond Phase 0 |
| 2 | Live read-only measurements: catalogue, sizes and statistics, index use, retention growth, query plans, job runtimes, copy-drift, orphan, and value-validity counts | Separate production-read approval; production available |
| 3 | Verify Suspected findings with targeted read-only diagnostics | Separate production-read approval per batch |
| 4 | Report and triage with the user | User review |

Phase 1 can run while production is unavailable. The pending PLAN-012
diagnostic (`.work/probe_plan012_observation_bloat.sql`) is reused in Phase 2.

## Coordination

PLAN-012's pipeline review is the Computer-domain seed and is consumed, not
repeated; its completion gate is unchanged. Findings route to PLAN-002/005/007
(collection, Jobs, ingest), PLAN-004/015 (identity), PLAN-006/008 (legacy
agent-compliance, Metabase), PLAN-011 (software), PLAN-012 (readers and
performance), and PLAN-014 (requirements) without changing their scope.

## Validation

- Every live-catalogue object appears in the inventory or its absence is
  explained.
- Every finding has a criterion, grade, evidence pointer, and routing.
- Plan registry validation and `git diff --check` pass at each checkpoint.

## Checkpoint

Defined 2026-10-23; status `ready`. Next action: user approval of Phase 0.
