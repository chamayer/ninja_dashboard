# PLAN-056 item 1 — Minimum Software implementation design

Status: Set aside. This draft over-selected mechanisms and is not an approved
or minimum implementation plan. Use the bounded change inventory in the
[implementation requirements](../records/PLAN-056-software-implementation-requirements.md#bounded-change-inventory--current-implementation-scope).
Date: 2026-11-11.
Authority: [ADR-0058](../../operations/docs/decisions/0058-software-summary-publication-contract.md).
Requirements: [M01–M14 / P01–P11](../records/PLAN-056-software-implementation-requirements.md).

## Result and necessary changes

Move the default Software overview's aggregate calculation into Software's
background publication path. Publish all overview aggregates together. The
request reads that completed result, configuration and bounded recent detail.
Existing installations, decisions, findings and catalog entities keep their
owners. This document proposes implementation choices; it does not change the
accepted contract or authorize runtime/test/schema/external execution.

| Necessary change | Requirement it satisfies | Existing code to reuse |
| --- | --- | --- |
| Background overview calculation with current-Computer title population | M01–M11, P01/P08 | Extract the reviewed overview aggregate SQL from `_software_page_data`; use `current_computer_sql`, `TITLE_STATUS_*` and `AWAITING_PUBLISHERS_SQL`. |
| One completed overview publication | P02–P04/P07 | Software refresh ownership and existing Jobs claims, coalescing and generation fencing. |
| Complete input-change and expiry maintenance | P05–P07/P09 | Inventory/classifier/catalog/intelligence completion paths, existing decision writers and Jobs admission. |
| Protected overview reader and honest unavailable/status copy | M02/M12–M14, P06/P08/P10 | Existing tenant middleware, effective-view security boundary, configuration helper and recent-install query. |
| Focused correctness and representative acceptance | P11 and ADR-0058 section 6 | Existing compatibility reader and targeted project checks. |

Do not add a second installation store, new classification engine, independent
per-installation counters, generic publication framework, worker service or
separate scheduling system. No Home/Products/CSV cutover is included.

## Reuse decisions

- Keep `software_title_current` and its other consumers compatible. Its current
  all-active-installation population differs from the required overview cohort.
  Changing it globally would also change the modal publisher used by safety;
  filtering its rows afterward cannot repair its within-title counts/publisher.
  Compute the required cohort once inside the existing Software owner's
  background calculation. Do not persist a second title/install inventory.
- Consume existing safety and capability outputs where their definitions match.
  Keep safety-band rules in their owner. Preserve missing-safety semantics.
- Derive cleanup counts from `v_device_software_exposure`, preserving its live
  decision precedence, per-type suppression and evidence/condition deadlines.
  Do not recreate the finding-to-installation exposure fan-out.
- Keep classifier findings and generation-fenced target consumption under
  `_software_reconcile`. Overview publication never acknowledges classifier work.
- Keep display names and recent details at their existing meaning. Recent
  detail may use its indexed LIMIT 10 query; labels must use a bounded indexed
  lookup, with a covering index only if the query review establishes it is
  needed. Do not replace a known source label with canonical text merely because
  a summary has not caught up.

## Publication storage and owner

The missing runtime object is **one completed overview row per tenant**. Store
the M01–M11 counts/highlight and its displayed label together, plus generation,
`computed_at`, `published_at`, input completion watermarks, source/assessment age
and window/exposure deadlines. Use typed nullable metrics and constraints for
nonnegative available counts. A successful empty publication contains zeros;
unavailable dependencies have explicit availability state, not numeric fallbacks.

Proposed relation: `operations.software_overview_current`, a regular derived
table with tenant primary key and FORCE RLS. A regular table permits atomic row
replacement and tenant enforcement without another independently refreshed
matview. `operations.v_software_overview` is the protected SELECT-only read
surface. No historical-generation store or current-title table is needed.

Completion and invalidation metadata are also necessary; choose their physical
placement only after reviewing the existing Jobs/input contracts. Jobs currently
records completed output revisions, but a completed run alone does not identify
the input snapshot used by an independently refreshed matview. Do not claim it
does or repurpose the classifier's single-consumer target acknowledgments.

The **single publication owner** is an overview entry point within
`ingest/inventory/software.py`, dispatched by a tenant-scoped Software overview
Job in the existing registry/worker. A separate short overview Job is justified
because an overview refresh must not require or wait for a full classification
merely to aggregate already completed inputs. Reuse existing execution capacity;
do not create another service or increase worker concurrency as part of this.

## Calculation and atomic replacement

1. Establish tenant context and a read-only REPEATABLE READ input snapshot.
   Capture the prior overview generation and actual input/completion watermarks.
   Compute the qualifying-title CTE once, retaining exact canonical grouping,
   modal-publisher ties and the shared Computer selector. Use its result for
   totals, status and membership-dependent category/risk/window calculations.
   Findings and exposure retain their own populations.
2. Use one captured `computed_at` for all window predicates. Calculate next
   window change and earliest relevant exposure deadline. Obtain all aggregate
   results in that snapshot. Reject an incomplete candidate; retain the last
   complete publication. An unavailable dependency is identified explicitly,
   never silently represented as successful zero.
3. Close the input snapshot. In a short write transaction, serialize this
   tenant's publication, then lock/check the actual
   `operations.operator_job_runs` row: tenant, definition, scope, running status,
   claim token, cancellation and deadline. Hold its lock through commit. Existing
   progress/heartbeat checks before calculation are not sufficient final fencing.
4. Compare the live overview generation with the captured base. A mismatch
   rejects the candidate; it cannot overwrite a newer publication. Atomically
   replace the whole row and acknowledge only the exact input versions included.
   Newer input changes stay pending for the existing queued successor mechanism.
   Recheck deadlines before exposing decision/expiry-sensitive results.
5. Complete the Job through the existing API. If the process exits between
   publication and Job completion, a retry is safe: it reads the new base and
   cannot clear newer invalidation. A publication failure leaves the prior row
   and original freshness evidence intact.

All components of one overview result share that publication boundary. Existing
safety/exposure refreshes need successful input receipts; they do not become
atomic simply because they ran before the overview Job.

## Input maintenance and next-read behavior

Every changed input must reach the Software owner without an overview request.
Use the actual persisted writers as the coverage boundary, including SQL/admin
paths. Input hooks signal invalidation/admission; they never calculate summaries
or synchronously refresh fleet matviews. Hooks must be transactional so a
rolled-back input does not claim a committed change, and committed changes are
not lost if an application callback fails.

| Input / current owner | Required publication work |
| --- | --- |
| `software_installations_current`; `inventory/software.py`, catalog relinking | Invalidate cohort/totals/status/category/risk/windows/labels on relevant insert, removal, stale/delete and field/link changes. Preserve complete-list and removal-hold guards. |
| `devices`, `set_source_association`, ownership projector | Invalidate affected population/scoped outputs on lifecycle, deletion, association and ownership changes without waiting for new inventory. Existing association authority remains unchanged. |
| Catalog products/versions and capability machine/operator assertions/rules | Recompute affected category/title results after the owner's completed projection. Descriptive taxonomy remains separate. |
| `cve_match`, `intel.cves`, `safety_signal`, aliases and safety policy | Existing safety owner refreshes on relevant changes, including scores/KEV when match membership is unchanged; publish its actual input receipt. |
| `findings`, `finding_types`, classifier settings | Maintain status/issue/prompt metrics for relevant detail/status/type/category/policy changes. Preserve classifier completion versus operator-write boundaries. |
| `software_decisions`; UI, bulk actions and imports | Invalidate decision-sensitive results in the saving transaction; preserve existing prompt resolution and approval precedence. |
| Readiness, assessments, active policy and source/evidence support | Keep exposure owner and deadline receipts current; policy/source changes must not wait for new inventory. |
| Time | Schedule summary/window maintenance from its next expiry; keep exposure expiry guarded on every read. |

For the initial reader, use ADR-0058's **explicit pending alternative** whenever
an effective decision is newer than the completed publication/required upstream
receipt. Show Updating for affected fields until covered. This avoids inventing
a second decision engine. It does not satisfy the 60-second publication target
by itself. Existing effective views continue to govern actions immediately.

The protected read checks publication, input/failure state and deadlines in one
statement snapshot. On missing publication show unavailable; on expired exposure
hide that retained count immediately; on overdue/failed summary mark affected
values stale/unavailable with retained timestamps. No request-time fleet fallback
or request-triggered rebuild. Preserve available unrelated values with explicit
availability; never present a mixed result as a single fresh generation.

## Admission budget: unresolved, necessary decision

The current durable schedule producer polls every minute; that alone leaves no
guaranteed execution budget under P05. Changes can use the existing transactional
Jobs request API and successor coalescing. Time expiry also needs bounded
admission through the existing scheduler. Before selecting an interval, review
the actual refresh cost as ADR-0058 requires:

`admission delay + queue wait + required input publication + overview build/commit <= 60 seconds`.

Do not adopt the earlier five-second callback or change acquisition cadence by
assumption. If existing Jobs admission cannot meet the budget, propose the
smallest scheduler-admission adjustment with its database load and recovery
impact. Representative timing requires separate external-run authorization;
workstation fleet timing is prohibited. Do not claim the freshness design is
operationally proven until this gate passes.

## Security, migration and validation

The migration review must supply exact table/view/function SQL, keys/checks,
RLS policies, fixed-search-path writer functions and explicit DML revokes.
Runtime roles read only the effective summary view. Narrow publish authority
validates the active Software Job claim; input hooks cannot supply an arbitrary
tenant. Retain the current `/software/` authorization and tenant context; do not
invent a new `is_staff` restriction or reuse fleet totals on client-scoped pages.
Ordinary permitted users, wrong/missing tenants and restricted scope need checks.

Additive migration creates empty publication storage and hooks without a fleet
scan. Check both migration tracks before enabling the new path. Initialize and
rebuild through the same governed owner; retain the old complete result until
replacement. Rollback restores the old reader through an authorized deployment
and disables new admission; it preserves decisions and underlying input stores.
Concrete command names and reversals must be supplied with the SQL review, not
documented as if unimplemented commands already exist.

Expected edits: Software owner/dispatch/registry, relevant persisted-input hooks
and owner receipts, Operations migration(s), a small overview reader in
`apps/core/software_overview.py`, `views.py` routing and `software_page.html`.
Keep Products/CSV on their existing path. Dockerfiles already copy runtime module
directories/shared code/migrations/templates; verify final packaging. No Compose
ports/entrypoints or dependencies need change on current evidence.

Validation follows the gathered requirements: same-snapshot metric parity and
small lifecycle/decision/NULL/isolation/expiry/failure/concurrency fixtures, then
authorized representative publication and full-page acceptance. Approval is
required before adding/changing tests. No runtime or SLO validation is claimed
by this design document. All 15 navigation items remain open.

## Current review gate

The reuse, calculation, publication and reader approach is specified above.
**This is not ready for implementation approval yet.** Remaining necessary work
is exact metadata placement/schema/privilege SQL, complete persisted-writer hook
enumeration and the maintenance-budget decision. Resolve those without adding
unrelated architecture. The earlier four-table proposal remains set aside.
