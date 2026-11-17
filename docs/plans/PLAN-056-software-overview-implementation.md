# PLAN-056 item 1 — Software overview implementation proposal

Status: Set aside; no mechanism in this draft is selected or approved.
Current work: [implementation requirements](../records/PLAN-056-software-implementation-requirements.md).
Date: 2026-11-11.
Contract: [accepted ADR-0058](../../operations/docs/decisions/0058-software-summary-publication-contract.md).
Active checkpoint: [PLAN-056](PLAN-056-platform-performance-assessment.md).

## Outcome and boundary

Make default authenticated Software overview HTML meet <=1.5 seconds ordinarily
and <2 seconds on the approved cold check, without request-time fleet aggregation
or a process-cache dependency. Preserve ADR-0058's populations, decision rules,
60-second publication bound and explicit unavailable states.

This proposal covers navigation item 1. It does not settle that item or authorize
items 2–15, Home cutover, a release, external execution or a rebuild. Products,
search, CSV, installation approval coverage and action eligibility retain their
existing contracts. No dependencies or universal summary framework are proposed.
All mechanisms below are proposed, not implemented or validated behavior.

## Confirmed implementation constraints

Reviewed against HEAD `ae45b463`, VERSION 0.144.11 and the current working files.
Existing uncommitted runtime and test changes remain excluded from this proposal's
implementation authorization; a later patch must be reviewed independently.

| Current source | Consequence |
| --- | --- |
| `operations/apps/core/views.py::_software_page_data` | Overview and Products share fleet title reconstruction, finding/status counts and window aggregates. Overview needs a separate default HTML reader. |
| `operations/apps/core/software_review.py::TITLE_STATUS_*` | Preserve exact title grouping, modal publisher, finding precedence and global investigate rules. `approve` means no open decision issue. |
| Migration 0293, `software_title_current` | Filters stale/deleted installations but does not join current Computers. Reusing its totals would violate ADR-0058. |
| `ingest/inventory/software.py::refresh_read_models` | Title and safety refreshes commit separately; catalog projection follows, with EOL projection afterward. This is not an atomic overview generation. |
| `ingest/operator_job_queue.py::_software_reconcile` | Exposure refresh follows successful classification. Target consumption compares captured generations; the overview must not consume these classifier targets. |
| `views.py::_refresh_software_risk_matview`, `software_decision_actions.py` | Decision paths currently request a best-effort safety refresh. That is not a guaranteed next-read or freshness mechanism. |
| SQL migration 114, effective exposure view | Approval precedence and evidence/condition deadlines are live guards. A published cleanup count needs immediate invalidation and an expiry guard. |
| `ingest/main.py` / `produce_due_schedules` | Ordinary Jobs admission polls every minute. A one-minute overview schedule alone cannot guarantee publication within 60 seconds. |
| `software_display.py`, migration 0126 | Recent detail has an existing first-observed index; label lookup currently sorts retained installations for requested names. Publish labels with title facts. |

ADR-0039 remains Proposed. Reuse the implemented installation coverage helper and
effective decision precedence; do not adopt its stronger overview wording as a
new approval definition. Change human copy for the legacy `approve` bucket to
**No open decision issue**. Keep the internal key and existing Products filters.

## Storage and sole writer

Use regular derived tables, not another independently refreshed matview.
Software owns one new background entry point,
`ingest/software_overview.py`, dispatched through Jobs as `software-overview`.
It alone writes the new current summary and title facts. Existing inventory,
catalog, classifier, safety and exposure owners keep their input ownership.
Do not replace or change the population/schema of `software_title_current`;
its other consumers retain compatibility. The companion current-title facts
represent the explicitly different ADR-0058 population.

Proposed relations, all in `operations`:

| Relation | Grain and required columns |
| --- | --- |
| `software_overview_dirty` | Immutable UUID `id` primary key; `tenant_id bigint`, `dependency text`, `changed_at timestamptz`. Index `(tenant_id, dependency, changed_at, id)`. No payload, title, customer label or per-installation counter. |
| `software_overview_input_completion` | Primary key `(tenant_id, dependency)`; `input_revision text`, `completed_revision text`, `completed_at timestamptz`, `source_as_of timestamptz`, `failed_at timestamptz` nullable. These are upstream owner receipts, not overview success timestamps. |
| `software_overview_current` | Primary key `tenant_id`; `generation uuid`, `computed_at`, `published_at`, `input_watermarks jsonb`, `source_as_of jsonb`, `window_expires_at`, `exposure_expires_at`, typed nullable metric columns listed below and `unavailable_dependencies text[]`. |
| `software_overview_title_current` | Primary key `(tenant_id, canonical_name)` with exact stored text grouping; `generation uuid`, `publisher text` nullable, `installations bigint`, `device_count bigint`, `client_count bigint`, first/last observation and latest-install timestamps, `weekly_devices bigint`, `has_capability boolean`, `safety_band text` nullable, `display_name text` nullable. |

Use existing tenant foreign keys; title facts are tenant-owned derived results,
not tenant-owned catalog entities. Check nonnegative populated counters, allowed
risk bands and `published_at >= computed_at`. Require all title rows to carry the
published generation; verify that invariant before commit. No independent title
writer, active pointer table, permanent generation history or per-installation
summary store is needed. PostgreSQL transactions provide atomic replacement.

Header metrics are nullable bigint columns: `installations`, `products`,
`categorized`, `uncategorized`, `status_reject`, `status_pending`,
`status_investigate`, `status_no_issue`, `risk_high`, `risk_medium`, `risk_low`,
`risk_clean`, `risk_unknown`, `active_issues`, `prompt_titles`,
`awaiting_publishers`, `cleanup_devices`, `weekly_products`, `weekly_high_risk`;
plus nullable `top_new_canonical_name text`, `top_new_devices bigint` and
`top_new_display_name text`. SQL NULL means unavailable, never zero.
Available empty results are explicit zeros. `user_risk_users` remains an unused
compatibility field and is not rendered as a measured KPI.

This is a whole-snapshot refresh function, not an incremental projector.
Title-fact storage is compact by title; it does not duplicate installation rows.
Its refresh cost is a cutover gate, not an assumed performance improvement.

## Population and aggregation SQL

The owner builds one consistent candidate in a read-only REPEATABLE READ
transaction with tenant context established first. Use the reviewed current
reader as the parity oracle; extract its SQL rather than inventing new semantics.
The core title SQL is:

```sql
SELECT i.tenant_id, i.canonical_name,
       mode() WITHIN GROUP (ORDER BY i.publisher) AS publisher,
       count(*)::bigint AS installations,
       count(DISTINCT i.device_id)::bigint AS device_count,
       count(DISTINCT i.client_id)::bigint AS client_count,
       min(i.first_observed_at) AS first_observed_at,
       max(i.last_observed_at) AS last_observed_at,
       max(i.first_observed_at) AS latest_install,
       count(DISTINCT i.device_id) FILTER (
           WHERE i.first_observed_at >= %(computed_at)s - interval '7 days'
       )::bigint AS weekly_devices
  FROM operations.software_installations_current i
  JOIN operations.devices d
    ON d.tenant_id = i.tenant_id AND d.id = i.device_id
 WHERE i.tenant_id = %(tenant_id)s
   AND i.deleted_at IS NULL AND i.stale_since IS NULL
   AND d.deleted_at IS NULL
   AND d.lifecycle_status <> 'retired'
 GROUP BY i.tenant_id, i.canonical_name;
```

The lifecycle predicate must continue to be emitted by `current_computer_sql('d')`
in runtime code, not copied into a second maintained selector. Do not introduce
recent-contact or resolved-ownership filters. Use one fixed `computed_at` across
all window queries, not a changing wall clock between components.

From this title candidate, sum installations and count products. Categorized
membership comes from the current installation/version/product/effective
capability join in `_software_page_data`; deduplicate exact canonical titles
before joining. Uncategorized is `greatest(products - categorized, 0)`.
Join existing safety rows by exact tenant/title and group their existing bands;
do not turn missing safety rows into unknown or clean. Multiple exact title keys
may intentionally share a normalized decision/label key.

Apply `TITLE_STATUS_CTES`, `TITLE_STATUS_JOINS` and `TITLE_STATUS` to candidate
title rows, parameterizing the tenant literals. Preserve rejected finding,
prompt, global investigate, then no-issue precedence. Preserve modal-publisher
ties and existing NULL behavior. This is title status, not installation coverage.

Findings metrics use the existing predicates independently: Software issue
category, active open/acknowledged/investigating statuses and exclusion of
`whitelist_suggestion`; prompt distinct JSON values retain SQL NULL versus JSON
null and exact case behavior. In particular, do not substitute
`count(DISTINCT details->>'canonical_name')` for the existing ORM distinct row
count. Awaiting publishers retain `AWAITING_PUBLISHERS_SQL` unchanged in meaning.

Weekly products count title candidates with `weekly_devices > 0`; top title
orders by weekly devices descending then canonical name. Weekly high risk uses
the existing high-band safety membership. Compute the earliest future
`first_observed_at + interval '7 days'` among qualifying installations as the
next window boundary; future-dated input also requires its window-entry boundary.
Preserve the existing inclusive `>=` window edge.

Cleanup counts `DISTINCT device_id` from the protected effective exposure view,
with open/acknowledged status and exclusion of `whitelist_suggestion`. Retain the
earliest evidence/condition deadline of eligible contributing exposures as a
conservative invalidation boundary. It is acceptable to invalidate earlier than
the distinct count changes; never retain it past an exposure deadline.

Labels use the current latest retained nonempty source spelling, including stale
rows, with the existing last-observed/display-name/device tie order. Build labels
once in the background for title keys. Recent installation labels absent from
the last published generation fall back to canonical text until publication;
if exact immediate label parity is required, use a reviewed covering lookup
index and a query limited to the ten displayed keys. Do not add an unmeasured
installation-wide label sort to requests.

## Atomic publication and Jobs fencing

1. Jobs admits one tenant-scoped `software-overview` run using the existing
   coalescing and active-scope guard, with its own Software overview resource key.
   Classification is not run by this handler. It does not consume
   `software_reclassification_targets` or acquire installation writer locks.
2. In the candidate snapshot, capture the existing header generation, visible
   dirty UUIDs, upstream completion receipts and one `computed_at`. Build all
   available metrics, title facts, labels and deadlines from that snapshot.
   Incomplete/failed upstream components yield unavailable dependent fields;
   their receipts are not advanced by the overview.
3. Close the read transaction. Candidate title rows and scalar results are held
   in worker memory, without raw installation payloads. Cancellation or failure
   here leaves the previous publication untouched.
4. In a short READ COMMITTED write transaction, take a tenant overview advisory
   transaction lock and validate/lock the existing Jobs run through its fenced
   claim mechanism. Reject wrong token, expired/revoked claim or cancellation.
   Hold that row lock until commit so a superseded worker cannot publish.
   Compare the current header generation with the captured base; if different,
   discard the candidate and retry from a new snapshot. Never overwrite a newer
   generation. Recheck time deadlines; an already expired candidate is retried
   or has affected metrics explicitly unavailable.
5. Replace this tenant's title rows and header in that same transaction. Delete
   only captured dirty UUIDs actually covered by available components; retain
   failed/incomplete dependencies. Updates committed after the snapshot have
   different UUIDs and remain dirty. Publish a new random generation identifier
   and the original snapshot/watermarks; commit once. No component refresh
   updates visible header fields individually.
6. Finish the Jobs run using its existing token API. If the process dies after
   publication and before Jobs completion, replay is safe: recompute against
   the current base and retain new invalidations. Failed publication rolls back
   both replacement and consumption. Idempotence does not depend on deleting
   a newly dirtied key by title or on wall-clock ordering.

Implementation must identify the current Jobs claim row/lease checks in reviewed
SQL; a heartbeat before publication alone is insufficient fencing. Do not hold
the Jobs row lock during candidate calculation or upstream refreshes.

## Dependency hooks and freshness

Install database invalidation hooks using statement transition tables where
supported. They append at most one event per affected tenant/dependency per
statement, in the input transaction; they do not lock or update summary counters.
Ignore no-op changes to relevant values. Capture both old and new tenants for
rekeys. Rollback removes invalidation with the input write. Application-only
`on_commit` callbacks are insufficient because SQL/admin writers would bypass
them. INSERT/UPDATE/DELETE hooks are separately defined where transition-table
restrictions require it. No TRUNCATE/rebuild path may bypass invalidation.

| Input family / existing owners | Required wiring and completion |
| --- | --- |
| Inventory: `software_installations_current`; `ingest/inventory/software.py` | Membership, counts, labels, windows, capability/risk joins. Hook actual insert/delete and relevant stale/deleted/title/publisher/version/device/client/observation changes. Existing complete-list guard continues to prevent inferred removals from incomplete collection. |
| Computer population: `devices`, association and ownership projection | Device lifecycle/deletion/client changes invalidate membership and scoped exposure. Association/ownership owners invalidate their affected output even when no installation arrived. Do not add a second association writer. |
| Catalog: `software_catalog.py`, `software_capabilities.py`, `intel/category_match.py`, Operations operator assertions | Version/product links and effective capability evidence/rules invalidate category membership. Record completion after successful owner transaction/publication, including operator assertion insert/withdrawal. Descriptive category remains distinct and is not a new overview metric. |
| Safety/intelligence: `cve_match`, `intel.cves`, `safety_signal`, publisher aliases and safety configuration | Refresh safety on scores/KEV/signals/policy changes even when match membership is unchanged. Owner receipt must match the actual successful safety publication; enqueueing or successful HTTP fetch is insufficient. |
| Findings: `findings`, `finding_types`; software reconcile and all operator status writers | Relevant details/status/type/category changes invalidate issue, prompt and title-status results. Bulk SQL and UI paths must both be covered. Classifier completion is a separate watermark from individual committed finding writes. |
| Decisions: `software_decisions`; UI, bulk actions and imports | Synchronous transactional decision invalidation; preserve existing decision keys, scope precedence and prompt-resolution behavior. Safety/exposure owners record successful recomputation against the captured decision input. |
| Configuration/readiness: `evaluator_config`, `software_device_readiness`, active condition policy and condition assessments; source support/evidence owners | Config explanations remain a small live read. Eligibility changes invalidate exposure-dependent results; record current policy digest and actual upstream assessment time. Do not make a stale assessment fresh by regenerating its summary. |
| Time | Persist earliest window and exposure deadlines. Discover due deadlines independently of inventory. Exposure count becomes unavailable on expiry immediately; refresh recomputes it from the effective view. |

The migration review must enumerate concrete tables, relevant columns and trigger
names for every row above, including catalog/condition tables installed by the
ingest migration track. The two startup migration tracks race today: do not
silently skip absent trigger targets. Keep cutover unavailable until an explicit
dependency/hook inventory check passes after both tracks are ready. This is an
implementation hold point, not permission to claim the matrix already enforced.

Propose one bounded APScheduler discovery callback in the existing ingest process
every 5 seconds, `max_instances=1`, honoring `SCHEDULED_JOBS_ENABLED`. It checks
indexed dirty/deadline state and requests/coalesces Jobs work; it performs no
aggregation, classification, network call or rebuild. Leave the existing minute
schedule producer and unrelated schedules unchanged. Declare the definition,
resource, recovery evidence and visibility in `shared/jobs_registry.py` and
dispatch in `operator_job_queue.py`. This narrow additional admission path needs
explicit implementation review because the current cadence cannot meet the SLO.

The 60-second budget includes discovery, queue wait, dependency publication,
candidate calculation and commit. Five-second discovery is a proposed budget
allocation, not evidence that the rest fits. Preserve the earliest dirty time
until covered; repeated changes or retries cannot reset lag. Normal summary lag
is allowed up to 60 seconds. Upstream acquisition/classification age is reported
separately. No every-minute full-fleet classifier is introduced.

## Decisions, failure and access on the next read

Choose ADR-0058's explicit pending alternative for the initial implementation.
A committed decision event makes decision-sensitive status, risk and cleanup
values **Updating** on the next request until the required current owner receipts
and new overview cover it. Never label the retained result decision-current.
This avoids raw installation reconstruction and a new parallel decision engine.
The pending behavior must be accepted with implementation; it is not a claim
that a live numerical overlay has been built.

Use one protected query that reads header plus indexed dirty/receipt/deadline
state in one statement snapshot. Validate tenant and permission before reading.
Missing publication displays **Not available yet**. Failed/overdue dependencies
display **Unavailable** or **Stale**, with the retained publication time and
source/assessment age. A dependency failure invalidates its fields immediately;
ordinary uncovered changes exceeding 60 seconds invalidate their dependent
fields. Exposure expiry is checked against statement time on every request;
no 60-second grace applies. Do not replace unavailable with zero/clean/healthy.
No request triggers work or falls back to the old fleet aggregate.

Recent installations may use the existing indexed, current-Computer/client join
with LIMIT 10 and the exact 24-hour predicate/order. Verify its plan and full
HTTP contribution externally; LIMIT alone does not prove bounded scan cost.
Configuration is a small live read. Default overview otherwise reads compact
protected results only. CSV stays on its existing path.

All four tables have tenant RLS with FORCE enabled. Owner is
`operations_migrate`; explicit revokes cover PUBLIC and runtime roles, with no
new retired-role grant. Runtime roles have SELECT only on security-barrier
effective views owned by the existing controlled view owner, never raw summary
storage. Revoke view DML explicitly. The worker gets only required read/write
privileges; narrow SECURITY DEFINER invalidation functions use a fixed search
path and cannot accept an arbitrary tenant from an untrusted caller.

The existing `/software/` handler has `login_required`; this alone does not prove
client-restricted authorization. Verify the actual access model before cutover.
Tenant-wide summary and labels are exposed only to callers authorized for that
population. A client-restricted caller must receive unavailable/denied fleet
results unless an explicitly reviewed scoped publication exists; do not filter
tenant-wide scalar totals after reading them or treat `is_staff` as an invented
replacement for the established permission model. Missing/wrong tenant, denied
client scope and ordinary permitted users require separate checks.

## Implementation slices and affected files

1. Review migration SQL: additive tables, RLS/grants, invalidation functions,
   complete concrete hook inventory, owner receipts and reversible DDL. Reserve
   numbers only against the actual migration heads; the excluded working 0406
   file is not authority to reuse a number. No bootstrap scan in migration.
2. Add Software owner/Jobs definition and dependency receipts to existing owners;
   add the bounded discovery callback. Keep reader cutover disabled while
   completeness, fencing, parity and recovery are checked.
3. Split default overview HTML from `_software_page_data`; add
   `operations/apps/core/software_overview.py` and protected read views. Update
   `operations/templates/software_page.html` for honest status and unavailable
   states. Preserve Products/CSV behavior and links; do not remove excluded work.
4. With separate authorization, bootstrap via the normal Jobs entry point,
   perform representative background and full-page acceptance, then enable the
   overview read path. Keep item 1 open until the user accepts its disposition.

Likely runtime files: the two new Software modules; `shared/jobs_registry.py`;
`ingest/main.py`, `operator_job_queue.py`, `inventory/software.py` and the owners
named in the hook matrix; Operations migration(s), `views.py`, the overview
template and decision action wiring. Update focused existing tests only with
explicit test-edit approval. Do not alter public endpoints or dependencies.

Both Dockerfiles already copy their complete runtime module directories and
`shared/`; Operations copies migrations/templates and ingest copies SQL. Confirm
the final artifacts contain all new files; do not rely on a SQL file under docs,
which `.dockerignore` excludes. No Compose port/entrypoint change is proposed.

## Bootstrap, rollback and recovery

Additive migrations create empty structures and short-lived trigger locks, with
bounded lock/statement timeouts; failure retries through normal migration review,
never disables invalidation. Large optional indexes use separate non-atomic
concurrent migrations. Do not perform a fleet scan during startup migrations.
New code must handle absent schema explicitly while the two services start.

Proposed packaged command shapes, not currently existing commands:

```text
python -m ingest.software_overview inspect --tenant 1
python -m ingest.software_overview request --tenant 1 --reason bootstrap
python -m ingest.software_overview request --tenant 1 --reason rebuild
```

`inspect` is bounded/read-only. `request` validates schema/hooks and requests the
same governed Job; it does not run a second refresh owner or delete current data.
Rebuild preserves the previous successful generation until atomic replacement.
Do not execute these shapes before implementation and explicit environment/run
authorization. No injected remote Python or manual refresh SQL is required.

Propose a default-off overview publication cutover setting. Rollback disables
the new reader/admission and restores the previous reader through a separately
authorized deployment; it retains derived tables and dirty evidence. Reverse
migrations remove only this feature's hooks/views/tables after reader/worker
rollback and explicit data-change authorization. Existing installation, catalog,
decision, finding and exposure stores are never truncated or rebuilt by rollback.

## Validation and approval boundary

First validate the concrete SQL and hooks, then run small synthetic parity and
failure checks. New/changed tests need approval because current coverage cannot
prove atomic replacement, missed invalidation, decision-pending reads or expiry.
Required gaps: exact case/NULL/publisher ties; empty/last install; stale/delete and
Computer lifecycle; capability/risk updates without inventory; JSON prompt
semantics; device/client/global decisions and partial coverage; tenant/client
isolation; 24-hour/seven-day/exposure boundaries; bootstrap/failure/retry;
concurrent invalidation and revoked claim; rollback/rebuild. Compare complete
metric results on one snapshot, not independent changing reads.

Workstation checks remain syntax/Django checks and small targeted database
fixtures. No full-fleet pass, local timing baseline or heavy backfill. After
separate authorization, measure representative refresh duration, contention,
queue wait and end-to-end 60-second lag, plus full Software HTML cold/ordinary
latency and unavailable-state behavior. Include ordinary-user access; prior
configured-admin HTTP evidence is insufficient. Record browser/network limits.

Do not enable cutover if hooks are incomplete, the refresh budget cannot be met,
access behavior is unresolved or correctness differs. If a whole-snapshot refresh
cannot meet the bound, return to design review with measurements; this proposal
does not authorize incremental counters or a new storage framework as a fallback.

Approval should explicitly cover the additive schema/privilege/hook design,
Software Jobs admission, separate overview reader, pending-state behavior and
focused test edits. Concrete migration SQL, hook enumeration and Jobs fencing
remain mandatory review hold points before schema execution. External runs,
bootstrap/rebuild, commit, push and deployment retain separate approvals.
