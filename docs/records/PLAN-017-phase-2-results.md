# PLAN-017 Phase 2 — Local mechanism results

Status: **complete; independently reviewed (Codex round 21, Point 41) with
qualifications applied.** Approved by the user on
2026-10-26 for Claude to execute the 12 checks in Point 40 (Codex round 20) of
[the review](../plans/review-plan-017-018.md), against disposable
testcontainers PostgreSQL only. No production access, remediation, schema or
migration change, deployment, commit or push occurred. Phase 3 is not
authorized by this result.

## Summary

| Outcome | Checks |
| --- | --- |
| Finding reproduced on current code | 1 F01, 2 F08, 3 F02, 4 F03, 5–6 U04 (both producers), 9 F07 (clean rebuild) |
| Mechanism holds | 7 first client publication, 8 first Computer publication, 9 in-place catalog repair, 10 closed-history expiry, 11 move / undo / reappearance, 12 tenant scope |
| New observations | 10: after expiry, history and daily presence disagree about a returning record's first sighting. 12: the 0066/0101 tenant policies raise on an empty tenant setting where later policies (`NULLIF`) return no rows — fail-closed either way |

Disposition changes proposed for review: **U04** moves from "candidate" to
"mechanism reproduced locally; production overlap and recovery cadence
unverified". **F07** moves from "code-confirmed contract mismatch" to
"reproduced in a disposable clean rebuild". F01/F02/F03/F08 keep their grades
with local reproduction evidence added. No severity changes are proposed here;
Phase 3 measurements decide incidence.

## Environment and reproduction

- Docker 29.6.2, `postgres:16-alpine` via `testcontainers[postgres]`, the
  repository `.venv` (pytest 8.4.2, psycopg 3.2.3).
- Check code: [`PLAN-017-phase-2/checks/`](PLAN-017-phase-2/checks/), outside
  the ordinary suite. From the repository root:
  `RUN_POSTGRES_INTEGRATION_TESTS=1 .venv/Scripts/python.exe -m pytest -p no:cacheprovider docs/records/PLAN-017-phase-2/checks -q`
  — final run after the Codex round 21 corrections: 34 passed; `ruff check`
  clean. Check-file sha256 prefixes: `activity_harness.py` a764b4e5972d,
  `conftest.py` 31f67b1adf9b, c01 91f7b8d1f25a, c02 68705233d918, c03
  02d6cea7765b, c04 0aab15d559d3, c05/c06 51e807a50715, c07 6da7c21529ec,
  c08 867d035541e3, c09 b41617c05ba8, c10 3fccc89e9dfb, c11 32994a56c964,
  c12 f10cc69bc9d6.
- A **reproduction** test asserts the current behavior a finding describes,
  so it passes when the finding is reproduced. A **control** asserts behavior
  that must stay correct.
- Existing harnesses also run: `ingest/tests/test_resolver_shared_serial_postgres.py`
  (1 passed), `ingest/tests/test_client_promotion.py` (5 passed),
  `operations/apps/core/tests/test_migration_0315_postgres.py` and
  `test_migration_0332_postgres.py` (11 passed; run from `operations/` with
  the repository root on `PYTHONPATH`).
- Source pinned at HEAD `03f71b6`; every path under test was clean against
  HEAD at start and end (sha256 prefix): `ingest/source_observations.py`
  a1650085fe46, `observation_runs.py` 5e41639f4103, `observations.py`
  0f3b0539fabe, `connectors/sentinelone.py` ef5968e0f17a,
  `activities/ingest.py` 27cd79d3e8af, `source_events.py` e21b6eb8d607,
  `inventory/queue.py` be05415b84c5, `intel/matcher.py` 9ba8ac6a581e,
  `inventory/software.py` 7c187dc790a1, `software_reconcile.py` f466e26539ed,
  `operator_job_queue.py` d2ad90e74880, `software_catalog.py` 6eea0f2c3800,
  `identity/client_resolver.py` a711245e9a4c, `identity/resolver.py`
  4769efb6d12c, `retention_observations.py` a9a7478f6efd; migrations 0074
  665ef5210993, 0123 722ee9ad5805, 0201 f94371c7e9c5, 0250 fd9239d1377d, 0339
  1f722129d226, 0341 9c0f2f8ab62d, 0342 efe27170f02d.

## Results

| # | Subject | Result | Evidence |
| --- | --- | --- | --- |
| 1 | F01 | **Reproduced.** An empty `_FETCHERS` result returns from `write_observations` before any transaction: no snapshot run, the prior active record stays active, and the run log records `ok=True, rows=0`. Counterfactual: the shared primitives with a complete zero-row run withdraw that record (current and history agree). Controls: a partial snapshot withdraws nothing; a fetcher failure records `ok=False`, raises `SourceObservationFailure`, and leaves evidence. | `test_c01_f01_empty_collection.py`, 4 |
| 2 | F08 | **Reproduced.** A failed `/sites` call is swallowed by `_fetch_sites`; returned rows carry no partial signal, so the run is `complete`/`is_complete_snapshot=TRUE` and withdraws the zero-agent site. After a successful retry the site is active again, but history keeps an interval closed by the failed run and a new episode from the retry. The two halves are tested separately: the real connector shows the missing signal, and the withdrawal/history half feeds the resulting rows through the real run primitives; the failed fetch was not run end to end through `write_observations`. | `test_c02_f08_partial_sites.py`, 2 |
| 3 | F02 | **Reproduced.** Page size 5 and cap 2: a 20-event backlog for one filter stores only the newest 10; the cursor jumps to the newest ID and the older 10 are never fetched later. Same loss when a capped filter shares `max_id` with a filter that drains. The cap is only a log warning. No IDs repeated, so no duplicate storage, capture or enqueue arose. Control: a backlog within the cap is fully processed. | `test_c03_f02_activity_cap.py`, 3 |
| 4 | F03 | **Reproduced.** Event capture and `_set_last_id` complete before `_enqueue_software_activities`; an interruption at the enqueue leaves the cursor past the `SOFTWARE_ADDED` event and a replay skips it, so no queue demand exists. The event is retained in `operations.source_events` (`processing_status='recorded'`), but no local consumer derives software demand from it; recovery depends on full inventory runs. Control: an uninterrupted run enqueues once. | `test_c04_f03_cursor_before_demand.py`, 2 |
| 5 | U04, inventory producer | **Reproduced.** Two independent connections: change → consumer capture (`PENDING_TARGETS_SQL`) → reconcile read → second change (`CHANGED_TITLES_SQL`) → acknowledgment (`CONSUME_TARGETS_SQL`). The second change hits `ON CONFLICT … DO NOTHING` on the captured row, the acknowledgment consumes it, and no pending demand remains although the read saw older evidence. Controls: a change after capture but before the read is seen by the read; a change after acknowledgment creates a new pending row. | `test_c05_c06_u04_target_ack_race.py`, 2 |
| 6 | U04, intel matcher producer | **Reproduced.** The matcher statement (read from `ingest/intel/matcher.py` at test time) hits `DO UPDATE SET queued_at = now()` on the captured row; `CONSUME_TARGETS_SQL` matches by ID only, so the newer `queued_at` does not protect the demand and the read missed the new match. The same two controls are exercised for the matcher (added after Codex round 21). | same file, 2 |
| 7 | First client publication | **Holds.** The real `promote_client_candidate_v1` (migration 0342) creates one entity-anchored provisional client and one source-tier alias and closes the candidate; the resolver's real `_attach_group` attaches the org and device evidence. Replay raises "not open" and creates nothing; mapping to an existing client creates none; two concurrent promotions serialize on the candidate row lock and publish one client. | `test_c07_first_client_publication.py`, 3 |
| 8 | First Computer publication | **Holds.** `write_current_rows` publishes one current row and one open history interval; a replay adds nothing. The real `_promote_unmatched_clusters` creates one Computer with its entity anchor; a replay creates none; an unattached sibling of the same source record attaches through the sibling guard; two concurrent promotions serialize on the `resolver_promotion` advisory lock. | `test_c08_first_computer_publication.py`, 4 |
| 9 | Catalog rebuild (F07) | **In-place repair holds; clean rebuild reproduces F07.** The real projector statements are idempotent and keep product/version UUIDs; a cleared link relinks to the same product and keeps the old version; RESTRICT blocks deleting a referenced version. A clean rebuild (unlink, delete catalog rows, rerun) does not recreate the catalog: the vanished-installation product is not recreated, the surviving product gets a new `product_uuid`, and authored references keyed by the old UUIDs dangle. The authored references are a stand-in table, so the dangling result is illustrative of the UUID dependency, not a test of the production authored-reference tables or their constraints. The docstring's "rebuilds it identically" holds only for in-place reruns. | `test_c09_catalog_rebuild.py`, 4 |
| 10 | Closed-history expiry | **Holds, with a history limit.** The real `purge_closed_observation_history` (0074) deletes only closed intervals before the cutoff and never an open version; a withdrawn record keeps its current row as anchor; daily-presence RESTRICT keeps current rows undeletable. For a record that disappeared and returned, the purge removes its first episode: history starts at the reappearance while daily presence still records the earlier day. | `test_c10_history_expiry.py`, 2 |
| 11 | Move, undo, reappearance | **Holds.** Computer merge → split (undo) moves links both ways in the existing real-migration harness (0315/0317 tests). For a client source group, the real `move_client_source_group_v1` (0341) with `decide_client_source_mapping_v1` (0201, deferrable per 0339) moves A → B → A: link, org and device records, alias and Computer return to A; link history keeps three intervals with `moved_from_client_id` provenance and one open row; the decision is superseded, not duplicated. The collector's real `_load_client_links` then maps the reappearing group to A. Moving to the current client is refused. | `test_c11_client_move_undo.py`, 3 |
| 12 | Tenant scope | **Holds.** With the 0066/0101 policies under FORCE RLS and plain runtime roles, two tenants with colliding source instance, namespace and external IDs each read only their own current record and client link (including through the `security_invoker` view); a cross-tenant insert and a tenant retarget are rejected by `WITH CHECK`; an update reaches only the caller's tenant. With no tenant context a fresh session reads nothing; a pooled session whose tenant was set earlier (also after `SET LOCAL`) raises on the `''::bigint` cast instead — fail-closed. | `test_c12_tenant_scope.py`, 3 |

## Interpretation and limits

- **U04.** The loss mechanism is in the shared SQL. Whether a findings job
  overlaps an inventory or matcher job in production is a scheduling question
  (their protected resource keys differ). The code's recovery is the next
  whole-fleet findings run (daily and after decisions), so the loss is bounded
  staleness, not permanent loss.
- **Schemas** are hand-built and checked against the named migrations:
  observation tables from `test_observation_dual_write_postgres.py`; target
  table per 0250/0277; catalog per 074/075/076; daily presence per 0097;
  decisions per 0201 + 0339; policies per 0066/0101; `v_client_source_link`
  per 0123. Database functions and SQL constants were read verbatim from
  source at test time. Omitted: most foreign keys to tenants/users/catalog,
  RLS outside check 12, grants outside check 12. The 0339 deferral was first
  missed and produced a false failure — a reminder that results depend on
  schema fidelity.
- **Stubs:** `begin_change` (change history not covered); the resolver's
  matcher, naming, agent-ID loading and layer entities (check 8 validates
  none of their behavior); `move_computer_to_client` reduced to the device
  update (check 11 does not validate that function's full production effects);
  authored catalog references as a stand-in table (check 9). Checks 3–4 use an
  in-memory feed following the documented `/v2/activities` contract with the
  database, run-log and queue boundaries patched, so they do not test commit
  ordering.
- **Not under test:** `ingest/identity/matching.py` (uncommitted concurrent
  changes); F04 (PLAN-012 completion-gate item 4); production incidence,
  catalogs and timings (Phase 3).
- **Full-migration build** was attempted at planning level and rejected: the
  ingest SQL migrations and Django migrations depend on each other in both
  directions (SQL 072+ reads `operations.*`; Django 0014 reads `ninja_core.*`)
  and production has never been built from empty.
- **Effort** stayed within the 4.0 engineer-day ceiling.

## Next action

Independent review of these results. Phase 3 (authorized production
measurements) needs separate explicit approval and should prioritize incidence
for F01 (empty `_FETCHERS` results), F02 (activity cap warnings), F08 (sites
failures) and U04 (findings/inventory/matcher job overlap).
