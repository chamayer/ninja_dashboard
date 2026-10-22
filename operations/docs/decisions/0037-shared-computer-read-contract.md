# 0037 — Shared Computer reads and inventory evidence

Status: Proposed
Date: 2026-10-21

## Context

PLAN-012 originally assumed another prepared inventory read model to improve
the Computers page. Local review found an existing Computer effective view,
`operations.v_device`, and inconsistent population rules in its consumers.
Clients includes retired Computers; Computer overview excludes them; Patching
does both in separate queries. Inventory labels a count of Computers and
additional source-record display rows as Computers. A new store alone would
preserve these errors if every page continued defining its own population.

`v_device` is a regular view over canonical Computer fields, stored session
state, patching scope, and operator decisions. Source presence and session
summaries are already materialized. Detailed inventory additionally needs
source/observation lifecycle, Hudu evidence, and evaluator-owned requirement
verdicts. These have different grains and freshness boundaries.

The last recorded inventory timing predates requirement-reader improvements.
No current measurement establishes that additional storage is needed.

## Options considered

- Make a new inventory store the authority for every Computer page. Rejected
  as the default: it duplicates the existing read boundary and can make
  identity, assignment, retirement, and operator decisions stale.
- Fix each page's predicates independently. Rejected: readers already drift
  despite sharing the same view; fixes need a shared selection mechanism.
- Keep one Computer read boundary, share population selection, compose
  domain evidence, and condition additional storage on measurement. Proposed.

## Proposed decision

### Computer facts and population

Retain `v_device` as the Computer read boundary, with one row per tenant and
Computer ID. Do not globally exclude retirement from that view: explicit
retired lists, history, and search need retained records.

A shared application reader owns population selection for page queries. Its
default is non-deleted and non-retired, including `pending_cleanup`. The
word "active" is not a synonym: recent contact is a separate time-based
metric using the applicable existing tenant/client threshold settings.
Retired/all scopes are explicit. Any necessary lower-level SQL selector is
defined once and reused by SQL/ORM adapters, rather than copied per page.

The proposed application home is `apps/core/computer_reads.py`. A scope
contains the tenant/access boundary, selected client IDs, explicit lifecycle
selection, and normalized Computer filters. Its selected-ID query is shared
by summaries, list queries, and exports; pagination is a separate argument
and never changes scope membership. Domain readers join that ID selection
to their own evidence. Keep population selection cheap: a basic Dashboard
count must not load the inventory's source/Hudu/requirement matrix.

Tenant/client access and selected filters constrain the population before
aggregation. Counts are distinct Computer IDs, independent of evidence
fan-out and pagination. Count links, destination lists, and CSV use the same
normalized scope. Fleet totals reconcile to the client breakdown plus
explicit buckets for unassigned Computers and Computers outside the visible
client directory, subject to the user's access. Excluded-client assignment
must not be represented as an unassigned Computer.

### Inventory evidence and counting units

Inventory composes existing effective evidence readers with the selected
Computers. Source records and requirements are child facts, not extra rows in
the Computer population. Pre-aggregate children before joining to avoid
inflating Computer counts. Preserve observation IDs and true link targets.

Evidence outside the selected current population stays visible under the
existing inventory filters, but is separately counted and described:

- a record with no Computer link;
- a record linked to a retired or deleted Computer;
- a record grouped next to a similarly named Computer for presentation only.

A displayed source-only row is not necessarily an unlinked record. Name
grouping never establishes identity or changes requirement satisfaction.
Count actual source records by observation identity when that is the metric;
count matching inventory rows when that is the metric, and label it as such.
The Computer metric counts only actual distinct Computer IDs. Hudu may have
several records in one displayed row, so physical records and rows are not
interchangeable units.

Source cards must declare whether they count Computers, evidence records, or
matching inventory rows. Totals need only match their corresponding filtered
destination under the same unit. Source cards overlap: one Computer can have
records in several sources, and source Offline is not the complement of
whole-Computer Online. Existing inventory filters and layout remain intact;
this proposal does not add controls or reorganize navigation.

### Status, requirements, and exceptions

Reuse existing presence/session authorities for availability and last contact;
do not create an independent status algorithm in the inventory projection.
Use their timestamps to distinguish refresh lag from population differences.
The existing whole-Computer false value means "No source reports online";
it is not proof of an explicit Offline assertion. Preserve that boolean for
compatibility and label its meaning accurately. Adding a three-state status
or changing which sources determine availability needs an explicit design
review and evidence, rather than being bundled into count reconciliation.
Do not infer an external device's real state from source collection time alone.

Requirements come from `device_requirement_state` under ADR-0035/0036.
Inventory assembly reads verdicts and joins current evidence; it does not
evaluate applicability, precedence, exemptions, or thresholds again.
Findings retain ADR-0023/0031 handling, assessment, and cover semantics.

Patching policy, software installations, and historical search remain
domain-specific readers. Their Computer membership uses the common contract
unless a documented exception applies. Scope-specific counts are legitimate;
their click-throughs must select the same Computer IDs and deduplicate
multiple installation versions. Search retains retired/former-identity matches
without increasing ordinary operational totals. Historical event counts retain
their event/time grain rather than being filtered through current membership.

### Performance and optional prepared data

First correct population selection, then measure the resulting inventory
database work, transfer, and rendering. Set an explicit performance target
and refresh cost budget using the same full-fleet/filter/card/CSV workloads.
Prefer set-based filtering/aggregation and page-bounded presentation first.

Only if evidence assembly remains a measured bottleneck, add a rebuildable,
inventory-specific projection behind the evidence reader. Its grain, owner,
refresh dependencies, invalidation paths, freshness, failure/recovery behavior,
and privileges must be reviewed before migration implementation. It may
prepare expensive joins, IDs, or aggregates from existing authorities, but it
must not become another authority for identity/lifecycle, operator decisions,
or requirement verdicts. Re-read current membership and authoritative verdicts
at the appropriate boundary; a stale projection must not resurrect a retired
or merged Computer. Do not add evidence fan-out to generic `v_device`.

Collection refresh through `refresh_derived()` is only one trigger. Assess
evaluator verdict writes and retirement, merge, assignment, and operator
decision paths too. Either compose those current facts at query time or
provide a declared invalidation/refresh path; do not assume another collection
will promptly repair them. Store evidence computation time separately from
`evaluated_at` and session refresh time. Preserve count/list snapshot
consistency using a single statement or a deliberate consistent snapshot
where concurrent changes would otherwise create mismatches.

## Enforcement required before acceptance as implemented

| Contract | Required mechanism |
| --- | --- |
| One Computer population rule | Shared reader/selector used by migrated consumers; membership checks include current, pending cleanup, retired, deleted, unassigned, and excluded-client cases. |
| No evidence fan-out | Aggregate children before joining; fixtures with duplicate agents, several Hudu records and software versions verify distinct Computer membership. |
| Counts open their own population | Compare complete card/summary scopes with destination IDs and CSV, including more than 500 Computers, before pagination. |
| Inventory units remain distinct | Explicit record/row kind and actual link identity; test same-name grouping and records linked to retired/deleted Computers. |
| No copied requirement rules | Read stored verdicts; verify applicable and non-applicable verdicts and covered findings against PLAN-014's implemented contract. |
| Tenant and privilege boundary | Runtime-role visibility checks with missing/wrong tenant context and existing client access; explicit DML revokes on new read views. Never assume a materialized view has RLS. |
| Performance justifies storage | Recorded before/after request and refresh measurements; reviewed refresh inputs, owner, age, failure and rebuild checks for any added projection. |

These are implementation acceptance requirements, not claims of enforcement
today. Runtime/schema changes and production validation have not been made by
this design revision.

## Rationale and consequences

Correctness depends on shared meaning as well as shared data. Reusing the
existing effective view preserves identity and operational behavior while
leaving inventory free to optimize its larger evidence workload. Pages can
remain focused without giving the same label different populations.

PLAN-012 must migrate consumers, not merely ship a new relation. The earlier
instruction to preserve inventory parity applies to valid evidence/filter
behavior; mislabeled mixed-row totals and inconsistent retirement filters
are explicit corrections with recorded before/after membership, not behaviors
to preserve. Additional storage may prove unnecessary.

## Supersedes or superseded by

Proposes a revision of PLAN-012's assumption that a new read model is required.
Builds on ADR-0003/0012 and DESIGN section 3.8; preserves ADR-0032/0034
identity/naming, ADR-0035/0036 verdict authority, and ADR-0023/0031 finding
semantics. Does not supersede those accepted decisions.
