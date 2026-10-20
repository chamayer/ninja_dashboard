# Jobs schema preparation review

Status: review record for the approved inert preparation slice. Migration
0183 implements that slice in the Operations migration graph; migration 0184
is its separately approved constrained activation follow-on. Neither has been
executed against a database.

SQL: `jobs-schema-preparation.sql` remains the reviewed standalone reference
for the **inert M1/M2 preparation slice**. Migration 0183 is its migration-runner
implementation. Migration 0184 is a narrow activation follow-on, not the
complete M1–M6 migration set. Neither has been executed. Do not interpret a
rollback terminator or checked-in migration as permission to test DDL on
production: locks and resource use can still affect the live service.

## Proposed changes and enforcement

| Object | Proposed enforcement / compatibility impact |
| --- | --- |
| `job_definition_versions` | Composite key/digest, bounded object metadata, immutable update/delete/truncate trigger. No runtime write grant; digest/content agreement is a future reconciler responsibility. |
| `operator_job_runs` | Nullable future-contract columns and default `contract_version=0`; CHECK rejects every nonlegacy version until a separately reviewed activation. Old status values and active-key uniqueness remain. |
| User/Job references | Tenant-composite unique keys and foreign keys; preflight rejects existing cross-tenant requester links. No ownership reassignment. |
| `job_requests` | Durable hashed request identity, tenant/definition/scope/run consistency through composite FK; actor tenant FK; append-only trigger. No runtime grants. |
| `job_schedules` | Tenant/definition/scope uniqueness, persisted anchor/revision, enforced disabled state. No seed or invented historical cadence. |
| `job_schedule_events` | Unique revision/due tick, durable reason/outcome, same-tenant links, immutable trigger. Request API must later enforce correspondence among the particular schedule, alias, run, and definition. |
| New tenant tables | Tenant-1 CHECK plus ENABLE/FORCE RLS; absent or empty context yields no matching policy. Arbitrary malformed context errors, not access. |
| Roles | 0183 revokes all new table/function privileges from PUBLIC and known runtime/reporting roles. 0184 grants only explicit `EXECUTE` on its security-definer definition-registration, request, and schedule-leader/claim APIs; it grants no direct new-table access. Existing runtime grants on legacy objects remain unchanged for compatibility. |

No privileged resource coordinator, new view, sequence, schema rename,
history deletion, worker service, process count, active-index replacement,
domain ownership backfill, schedule seed, or live schedule activation is
included. 0184 permits enabled schedule state only through later schedule
configuration; it creates no schedule row and activates none.

Proposed bounds (review choices, not previously approved settings): 64 KiB
definition/revision objects, 4 KiB cadence, 120-character definition/version,
256-character normalized scope, SHA-256-shaped digest/request identity.
Shape checks do not prove a digest was computed from the right content.
Typed scope FKs, payload schemas, allowed transitions, version immutability,
permissions, and resource fencing belong to the later admission API, which
must exist before the preparation-only CHECK constraints are replaced.

## Privilege matrix

| Objects | Owner | Runtime roles during preparation | Tenant policy |
| --- | --- | --- | --- |
| Definition versions | `operations_migrate` | No privileges | Global metadata, no tenant values allowed by reconciler |
| Requests, schedules, schedule events | `operations_migrate` | No privileges | Forced context-bound RLS plus tenant-1 CHECK |
| Mutation-rejection trigger function | `operations_migrate`, SECURITY INVOKER | No direct EXECUTE grant | No data access; raises only |
| Existing Jobs/users | Existing owner, verify before applying | Existing grants preserved | Existing policy plus added FK consistency; no claim of fixing all old writers |

Review actual role memberships/default privileges before converting this into
a migration. Explicit revokes from named roles do not remove access inherited
through an unexpected role membership. The preflight executor must see all
tenant rows; an RLS-limited count of zero is not proof of global consistency.

## Locks, ordering, and rollback

- Apply only after the then-current Operations migration graph; baseline
  currently ends at 0182. This draft reserves no migration number.
- New-table creation does not scan old data. Added constant/default and
  nullable columns preserve old values, but ALTER TABLE still takes locks.
  Exact rewrite behavior depends on the deployed PostgreSQL version.
- Composite unique indexes on users/Jobs and requester FK validation inspect
  existing rows. A quiescent window or separately reviewed concurrent-index
  preparation may be necessary if size or contention warrants it. The draft
  chooses neither based on the small historical Job sample alone.
- The two-second lock and 30-second statement limits bound each statement,
  not the entire migration or deployment. A failed statement must abort the
  migration transaction; do not retry live DDL automatically.
- Before activation, application rollback leaves additive objects in place.
  Prior writers still insert contract version 0 and use the unchanged active
  index. The new same-tenant requester FK can reject a previously tolerated
  invalid write; that is an intentional integrity gate, not full behavioral
  equivalence. Check existing callers before release approval.
- Do not write a reverse migration that drops new ledger/alias history. After
  any converted work exists, old-code rollback requires executor quiescence
  and external-outcome reconciliation; this draft does not authorize it.

## Remaining implementation requirements

The complete gate still needs resource/dependency/worker schema, domain attempt
links and verified ownership, event protection, constrained transition APIs,
read permissions, deployed-role checks, a numeric process/connection budget,
safe cutover fencing, and focused local PostgreSQL validation. None is proved
by static SQL review or by the four inventory tests.

The per-handler audit also found partial-success collection, disabled/busy
normal returns, swallowed resolver/retention/EOL failures, and external sends
whose failure is represented by values rather than exceptions. Future registry
metadata must describe these as unavailable/unreviewed contracts until the
corresponding adapters are implemented, not certify them by declaration.

## Sequencing

This review follows the active plan as written. The user approved the Step 1.2
architecture/inert scope, then separately approved the narrow 0184 activation
scope. Registry work is complete. Runtime dispatch, schedule reconciliation,
worker, resource, dependency, domain-link, and cutover work remain governed by
their later plan steps and their own migration/deployment approvals.
