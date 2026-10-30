# PLAN-003 — Technical package review

Status: implementation-readiness audit complete. R1–R4 have enforceable design
contracts; both product decisions are approved. The plan is ready to begin
scoped implementation. Migration execution, live preflight and deployment remain
separately gated. 2026-10-27.

Scope: current technical design, consumer ledger and proposed ADR-0046 checked
against current repository consumers and startup behavior. This is a design
review, not migration execution or runtime acceptance. Preserve unrelated work.
The findings do not reopen settled operator decisions. Readiness removal and
the `device_unenrolled` alertability change were explicitly approved after this
review and are now part of the current design contract.

## R1 — P1: Define the compatibility population during the storage-only release

[Technical design lines 23–28](PLAN-003-technical-design.md#1-scope-and-implementation-order)
put storage conversion before replacement of separate queue assembly. M4 copies
admin rows into findings while retaining an admin_findings compatibility view.
The phrase "common read adapter" does not specify how existing direct ORM reads
are kept disjoint during that intermediate release.

Current `views.py:1539` adds Finding and AdminFinding counts; `views.py:4259`
starts from all findings while `views.py:5837` separately reads admin findings.
After the proposed copy, an unchanged reader can see an admin row through both
paths. Merely replacing the SQL view does not change these direct ORM queries.

Required revision: explicitly assign these readers to slice 1, define either
temporary namespace-disjoint legacy reads or a single population, and require
identity-set/count assertions on the intermediate release, including home and
domain counters. Slice 2 can retain ownership of the new presentation.

Second-pass result: AST inventory lists every direct runtime
`Finding.objects`/`AdminFinding.objects` callsite and groups them into entity
reads/action targets and admin compatibility reads. The ledger covers home and
navigation counters, queue/domain counts, exports, Admin Health, action/review
links and scoped details. M2–M4 are one drained artifact; no service observes
the copied population before adapters and exact-set assertions are live. Raw SQL
paths remain mapped to their owning producer/consumer modules in the ledger.

## R2 — P1: Connect live relationships to execution authority

Technical design lines 177–210 define relation projection and say Requires
gates the relevant action, without specifying which action is gated or the
enforced relationship check at execution time. The consumer ledger preserves
guards but does not define how live relationships participate in them.

`ingest/source_actions.py:136` rechecks evidence and may_execute assessments;
`ingest/notifications.py:103` similarly rechecks may_notify. Neither current
contract knows about the proposed relationship records. A newly established
prerequisite need not invalidate an otherwise fresh old assessment. Hiding a
covered child in queue selection also does not itself stop its notification.

Required revision: define action applicability and a live relationship guard
used by request handlers, workers and delivery checks, including what changes
invalidate previous authority. Specify which review/handling actions remain
available. Preserve domain evidence and permission checks. Add acceptance cases
where a relationship changes after assessment or after work is queued.

Second-pass result: rule schema records registered gated action keys,
notification suppression and the parent-satisfaction predicate. Requires must
name at least one action; there is no implicit all-action behavior. Delivery or
source mutation rechecks current rule and relationship versions. The consumer
ledger maps current domain actions to closed effect keys. M3 preflight reads
every configured rule, requires an explicit mapping/manifest disposition, and
aborts on an unknown action or scope rather than guessing.

## R3 — P2: Specify graph lock ordering and the unchanged-input fast path

Technical design lines 189–200 propose a transaction-scoped tenant graph lock
and invoke the projector from input statement triggers. They do not state when
the lock is taken relative to finding/assessment/participant row locks, or
whether unchanged assessments take it.

If an AFTER trigger takes the graph lock after its statement has locked rows,
one transaction can own the graph lock and need a row already held by another
transaction waiting for that graph lock. Even without a deadlock, holding a
tenant-wide lock across a large evaluation can stall unrelated actions.
ADR-0031 already records significant evaluation/state-update cost and requires
an unchanged-assessment touch path. This review identifies an unresolved lock
protocol, not an observed production deadlock in unimplemented code.

Required revision: document a consistent lock acquisition protocol, bound the
work under the lock, and explain when the unchanged fast path avoids graph
serialization. Test concurrent evaluator/operator/rule changes and measure
contention in rehearsal; opposing-edge insertion alone is insufficient.

Second-pass result: repository evidence supports a feasible enforcement design,
not advisory convention alone. PostgreSQL 16 provides transaction advisory
locks and exposes held advisory keys in `pg_locks`; it explicitly leaves their
use to the application. Migration 0185 already takes a transaction advisory
lock before graph queries. Migration 0332 demonstrates tenant-checked
`SECURITY DEFINER` mutation functions, hardened search paths, revoked table
DML, and narrow EXECUTE grants. Conversely, 0161 directly grants assessment
and participant DML, so those grants must be replaced for graph inputs.

Design correction: revoke direct runtime DML on graph-affecting tables and
route writes through tenant-checked, versioned `SECURITY DEFINER` functions
owned by a restricted `NOBYPASSRLS` role. Each takes the reserved tenant lock
before row locks and runs the projector transactionally. Triggers check the
caller backend's held key in `pg_locks`; they do not acquire it. A deterministic
namespaced 64-bit hash can only cause unrelated tenants to serialize on
collision, not let one tenant bypass its lock. Concrete function/grant SQL and
PostgreSQL role/concurrency checks are implementation validation gates, not
unresolved architecture. See [PostgreSQL 16 advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS),
[system lock functions](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)
and [`pg_locks`](https://www.postgresql.org/docs/16/view-pg-locks.html).

## R4 — P2: Make release boundaries executable

Technical design lines 288–325 list M1–M6, but only M4 publishes the contract
version. M5 changes semantics and M6 must wait for a later rollback-window
decision. `operations/entrypoint.sh:61` applies every pending Django migration;
descriptive stage labels do not hold back files shipped in the same artifact.

The proposed M1 number 0354 is also occupied in the current worktree by
`0354_software_installation_display_name.py`, depending on migration 0353.
This unrelated work must be preserved, not overwritten or implicitly branched.

Required revision: list the migration/code artifacts in each release, reserve
M6 for its separately approved release, define required writer contract versions
for later semantic stages, and allocate migration dependencies against the
current graph at implementation time. Do not infer that M4's gate alone makes
later-stage workers safe during later migrations.

Second-pass result: M2–M4 and matching code are one drained artifact; M5 and M6
are separately approved artifacts. The consumer ledger maps Operations,
`ingest/main.py`, `ingest/jobs_worker.py`, notification dispatch/digest and
source-action execution to exact contract gates. All repository runtime
binaries both read and write, so each requires the exact generation; none uses
a compatibility range. DB boundaries reject stale compiled callers. The
mandatory drain handles already-running old processes because a caller-supplied
version is not process attestation.

## Revision disposition

The technical design and proposed ADR-0046 now specify these remedies:

- **R1:** Until slice 2, retain separate page assembly and require namespace-
  disjoint entity/admin reads. M4 compares exact identity sets, home/domain
  counters, disjointness and union conservation with the pre-cutover baseline.
- **R2:** Rules carry registered action keys and explicit notification behavior.
  Check live relationship and rule versions at request creation, worker claim
  and final delivery/mutation. Cancel or re-evaluate stale authority; preserve
  review/handling. Add post-assessment and post-queue link-change cases.
- **R3:** Call a tenant lock function before row locks and make triggers assert
  lock ownership. Order multi-tenant locks, use the no-lock touch path for
  unchanged assessments, bound traversal, and measure contention in rehearsal.
- **R4:** Package M2–M4 and matching code in one drained release artifact so no
  intermediate copied population is served. Gate processes on monotonic
  contract versions; require separate artifacts/approvals for M5 and M6. Assign
  migration numbers after rebase; preserve occupied 0354.

These are design resolutions, not implemented enforcement. The design requires
exact writer generations and database rejection of stale callers. The consumer
ledger now classifies direct ORM callsites, repository process entrypoints,
action keys and effect paths. M3 preflight must map every live configured rule
to those effects and abort on unclassified data. Concrete database grants,
functions and concurrent PostgreSQL role validation are required during scoped
implementation before migration approval or execution.

## Product decisions resolved by the user

1. **Readiness:** remove its column, filters, subgroup, count and sort behavior.
   This supersedes the earlier approval for Readiness controls. Preserve
   execution/evidence guards.
2. **`device_unenrolled` alertability:** its current flag is true. Its approved
   inventory/lifecycle-review meaning is not a protection-gap alert; M5 changes
   the flag to false while M1–M4 preserve the current flag.

These product decisions are resolved. M5 implementation/release remains subject
to its existing technical, migration, rehearsal, and deployment gates.

## Validation and disposition

R1–R4 have revised design remedies; none is implemented. No runtime tests,
migrations, production data reads, evaluator runs or source actions were run for
this review. Documentation validation is recorded in the active blueprint.
VERSION and CHANGELOG remain unchanged because no release is prepared.

## Next-session handoff

Start in `ninja-dashboard`. Read the PLAN-003 registry entry and module blueprint,
then this review and the current design/technical package. Verify current Git
status and migration dependencies before relying on recorded file locations.
Complete the callsite/process/action inventory and PostgreSQL lock/privilege
validation before implementation. Preserve the approved Readiness and
alertability decisions and retain implementation/deployment gates.
Implementation, migration execution, commit and deployment remain separately
gated. The findings and design documents are saved locally but uncommitted;
preserve them and unrelated work when starting the next session.
