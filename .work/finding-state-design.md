# Finding state: design (awaiting approval)

Status: proposal. Supersedes `.work/finding-attention-spec.md`. Nothing in this design is built.
Written 2026-10-15 after the Issues page work shipped migrations 0297-0300 and measured them.

## 1. Why a new design

Migrations 0297-0300 stored a rolled-up value on `findings.attention` but kept pause, freshness and
"critical takes priority" as a read-time view (`finding_states`). Measured on production
(2026-10-15, filtered Issues page, 36.4 s total, 34.9 s database, 1.5 s Python, 27 queries):

| Time | Query |
| --- | --- |
| 17.0 s | fleet counts by Type and state through the view |
| 8.3 s | filtered COUNT(*) using a view subquery |
| 7.4 s | per-Type counts using a view subquery |
| 1.6 s | a second view count |
| < 1 s together | the other 23 queries (rows, filters, side tables, OS choices) |

The view is the whole problem. A grouped count by Type and stored attention directly on `findings`
takes 137 ms for the 39,422 active findings; paused count takes 1.3 ms.

Principle: state is a stored fact, written in the same transaction as the change that caused it.
A page reads it; it never derives it.

## 2. What the page needs on load

Landing (no selection): seven tiles (unresolved, needs action, blocked, pending, covered, paused,
software decisions); the Type x state count matrix (about 60 Types x 3-5 states); three small
side tables (data collection problems, record-matching issues, records needing a match).
A selection or filter: one page of 50 rows (severity, finding, subject, context, status with state
label, reason, "N covered", critical-issue badge), the filtered total, the matrix recounted for the
filtered set, sorting and column filters.
Only the tiles and the matrices are fleet-wide, and all of them are counts.

## 3. Decisions

- Dropped (user, 2026-10-15): "critical takes priority" as a state. Critical findings sort first and a
  row shows a badge "Critical issue on this computer" (looked up for the 50 visible rows only).
  Visible effect: Blocked about 714 -> 447, Needs action about 5,389 -> 5,656 (the 267 findings the
  rule held back return to where their own evidence puts them).
- State has one writer (a function) and lives in its own narrow table, not as columns on `findings`.
  Recommendation, to confirm: a table enforces "one writer" by privilege, keeps the finding record
  free of derived data, and stays small for grouped counts. Cost: one more table and a column drop.
- Staleness is prevented by hooks in the same transaction (section 5), not by a schedule.

## 4. Data model

`operations.finding_state` (new):

| Column | Meaning |
| --- | --- |
| finding_id uuid PK, FK findings | one row per finding |
| tenant_id | row-level security, same policy shape as other tenant tables |
| finding_type_id | copied so counts need no join |
| attention | needs_action, blocked, pending, covered; NULL when the finding is closed |
| reason | short code of the deciding rule (for example `covered_by:device_offline`) |
| covered_by uuid[] | the open findings that cover it, empty otherwise |
| policy_version | the active policy version it was computed under |
| computed_at | when it was computed |

Indexes: (tenant_id, attention, finding_type_id) partial where attention IS NOT NULL;
(finding_id) primary key. Privileges: `operations_app`, `ninja_ingest`, readonly roles get SELECT only;
the function owner alone writes.

Not stored: pause, acknowledgement, resolution (columns on `findings`); time and policy-version
freshness (predicates, section 6).

## 5. The writer and its hooks

`operations.refresh_finding_state(uuid[])` is the only writer. It computes the rule (today's
roll-up from migration 0297, unchanged: every expected non-context participant has a current
assessment that may execute -> needs_action; any blocked -> blocked; a current `covered_by`
assessment whose covering finding is still open -> covered, with the covering ids stored in
`covered_by`; otherwise pending) and upserts the rows.

Hooks (database triggers, so no code path can skip them):

| Input changes | Trigger |
| --- | --- |
| An assessment is written | AFTER INSERT OR UPDATE on `condition_assessments` (row-level, one finding) |
| Participants are reconciled | AFTER INSERT OR DELETE on `condition_participants` (statement-level, batched) |
| A finding is inserted or its status or severity changes | AFTER INSERT, AFTER UPDATE OF status, severity on `findings` |
| A covering or covered finding's state changes | cascade inside the writer: refresh the findings that the changed finding covers (same computer, types in `finding_types.covered_by`, chains followed), bounded by a recursion guard |

Locking: rows are refreshed in `finding_id` order so concurrent evaluators cannot deadlock.
Closed findings: attention becomes NULL in the same transaction.

## 6. Reads

Everything below is an indexed predicate or a grouped count; nothing is computed per finding.

- Paused: `findings.snoozed_until > now()` (index exists).
- Closed: `findings.status`.
- Fresh: `computed_at >= now() - freshness window AND policy_version = active version`;
  otherwise the finding reads as pending. (A comparison of two columns, not a computation.)
- Tiles and matrix: `GROUP BY finding_type_id, attention` over `finding_state` joined only to
  the paused predicate; filtered matrix: the same restricted to the filtered finding ids.
- Attention filter: `finding_id IN (SELECT finding_id FROM finding_state WHERE attention = ...)`.
- Covered hidden by default: `NOT EXISTS (... attention = 'covered')`.
- Row detail (50 rows): state, reason, covered_by ids, plus the critical-issue badge (one query for
  the visible rows) and the "N covered" count (existing query).
- Sort by status: ordered by a CASE over `finding_state.attention` and the paused predicate.

## 7. What is removed

After the page is switched and has run clean for a day (separate deploy, rollback-safe before it):
view `operations.finding_states`, function `finding_live_attention`, model `FindingState`,
`findings.attention` and `findings.attention_at`, the 0297 `findings` triggers and functions
(replaced by section 5), `_condition_operator_states` and its Python projection,
`_fleet_condition_state_counts`, `_covered_finding_ids` and the "critical issue takes priority"
text. `_condition_response_ids` stays for the device page until that page moves.

## 8. Consistency check

The existing hourly check keeps its shape: recompute every active finding with the writer's
compute function and compare with `finding_state`; each disagreement is stored in
`finding_state_drift` (what was stored, what the rule says, when) before repair, and is logged.
Because the hooks run in-transaction, a mismatch means a missed input; it is a bug signal, not
routine repair. An operator-visible list of drift rows is in scope as a small read-only admin page.

## 9. Fence

Notifications, the digest, source actions, the software exposure read model and the evaluators keep
reading assessments exactly as they do. Moving any of them to `finding_state` is a separate
decision.

## 10. Deploys

1. Migration 0301: `finding_state`, the writer and compute functions, the triggers, the fill
   (about 8 s at 39,000 findings), privileges and row-level security. Same deploy: the Issues page
   reads `finding_state`; the view and old columns remain, unused. Rollback: revert the commit.
2. After a clean day: migration 0302 drops the objects in section 7; code removed in the same commit.

Each push approval names its migration. The migration fill and the first page loads are checked
before the next deploy.

## 11. Validation

- Disposable Postgres tests (same harness as `test_migration_0297_postgres.py`, with production
  column types): each input in section 5 changes the state in the same transaction; cascade up a
  chain; concurrent refresh order; closed findings; privileges (app roles cannot write).
- Production, read-only: the compute function against the current stored `attention` for all active
  findings (expected: equal; the 267 critical-held findings are the only intended change to
  the page counts).
- Timing targets on the deployed page (same staff-session harness): landing <= 1 s, filtered
  Issues pages <= 3 s, with per-query timings printed for any page over 3 s.
- Ratchet tests: nothing outside the writer writes `finding_state`; the page does not name the
  removed objects.

## 12. Risks and open items

- Trigger cost on `condition_assessments`: about 65,000 writes per full evaluation pass, each a
  one-finding refresh; measure before push (the per-call cost in `record_assessment` today is the
  baseline).
- Cascade cost and locking on large status changes; bounded by the recursion guard and ordering.
- A deploy while a heavy page query holds a lock on the view blocks the drop in deploy 2; the
  drop waits behind running queries, as 0299 and 0300 did.
- Not built: reassessment of children when a parent clears (they read pending until the next
  evaluator run); no admin surface for drift beyond the read-only list above.
- Fixed in passing: the 0299 failure came from a view column type (`varchar(120)`) that the test
  harness did not match; the harness now uses production types, and new migration tests must too.

## 13. Decision needed

Approve this design (including the table rather than columns, the staging in section 10, and the
count shift in section 3). No code until then.
