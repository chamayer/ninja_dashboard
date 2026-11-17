# PLAN-056 — Coverage presence selection

## Scope and reasoning

User requested a two-minute fix without losing page data. Implement a narrow
query correction in operations/apps/core/views.py; no full selector rewrite,
schema, cache, dependency or release. Registry owns plan status.

The stored-requirements query aggregates all tenant presence before joining
verdicts. Only satisfied verdicts use presence.online; all other status branches
are independent of it. Restrict that aggregation to presence rows matching an
existing satisfied device/entity/platform requirement (including platform any).
Use EXISTS so duplicate requirements cannot multiply presence rows. Tenant
predicate stays inside both inputs. The outer requirement population, ownership
checks, ordering, tuple shape and every output field remain unchanged.

## Steps and validation

Apply the semijoin before grouping; run syntax/system and whitespace/governance
checks. No new test files. Review the missing/stale/nonapplicable branches,
named versus any-platform matches and empty requirements. Performance and
deployed content parity require subsequent authorized verification; no speedup
or full R1–R9 certification is claimed from source review.

## Checkpoint

Implemented the 12-line semijoin in the initial requirements query only. Django
base-settings system check, registry validation and git diff --check pass.
Source review: non-satisfied statuses never read online; satisfied named keys
retain all exact-platform presence, and satisfied any keys retain all platforms
for that device/entity. Empty/no-satisfied state leaves all outer verdict rows
intact. No fields, filters, population or detail/export path removed. Existing
Dockerfile includes views.py. No schema or release change; uncommitted.

PostgreSQL query execution/parity is verified below; speed improvement and
full rendered-page acceptance remain unverified. Next review for release.
The wider compact-selector proposal is not delivered by this bounded slice;
remaining Coverage reads and fleet work stay open under PLAN-056. R1–R4 intent
is preserved by unchanged outer selection and a semijoin without fan-out;
R5/R8 performance acceptance remains open. No prepared-result lifecycle added.

## Parity verification scope

User authorizes parity verification. Compare complete original/candidate query
row multisets in one PostgreSQL repeatable-read, read-only snapshot through the
Operations runtime role and tenant context. Extract exact statements from Python
ASTs and verify deployed original matches HEAD. Eight-second statements,
one-second locks, 30-second process. Emit aggregate counts/booleans only.
No candidate deployment or production-data writes; remove exact staging files.
Verification complete; results below.

## Parity results — 2026-11-17

Verified exact AST-extracted original against deployed .27 before execution.
Actual operations_app role, tenant 1, repeatable-read/read-only transaction:
19,089 original rows and 19,089 candidate rows; all 11 column names match;
complete row multisets match exactly, including duplicate multiplicities and
every returned field. Zero lost rows and zero added/changed rows. No values
were emitted. Connection closed normally. Source shows only the presence
semijoin changed; all downstream page/filter/export code is unchanged.

Current data includes satisfied, missing, stale, OS-unknown, outside-coverage,
pending-cleanup and exempt verdicts, but no any-platform requirements. Therefore
also ran the exact two statements over read-only SQL VALUES/CTE fixtures (no
tables/data created), replacing only input relation names. Eleven output rows
match exactly and expected statuses pass: named and any-platform requirements,
multiple sources, duplicate/null/absent presence, mismatched entity/tenant,
non-satisfied verdicts and exempt exclusion. Fixture expected OS/cleanup labels
were corrected to preserve the original query's existing encoded literals;
the original and candidate always agreed, including during that fixture check.

Exact temporary host/container staging removed and absence confirmed. No
production data, serving files, migrations or Jobs changed. No permanent test
files created. This verifies the changed query's output; no full HTML/filter/CSV
execution matrix, performance comparison or sustained behavior is certified.

## Release checkpoint

User approved commit and push. Prepare 0.144.28, push origin then mirror;
origin push includes automatic deployment. No new migrations, dependency,
Compose or Dockerfile changes. Earlier 0420/0421 were confirmed applied on .26.
Include the retained .27 measurement/diagnosis evidence and updated handoffs;
preserve unrelated untracked recovery scripts. Next observe automatic rollout;
performance/full-page acceptance remains open. No separate redeploy.
