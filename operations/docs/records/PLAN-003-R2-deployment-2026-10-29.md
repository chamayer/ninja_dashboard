# PLAN-003 R2 — deployment record (0.132.0–0.133.1)

Date: 2026-10-29. The user approved the release, backup, drain and push, then
authorized autonomous completion. No production-copy rehearsal (user decision).

## Sequence (EDT)

- Pre-window: 39,991 active findings recorded across 52 namespace/type pairs.
- 18:14 ingest and Jobs worker stopped; no active database sessions remained.
- 18:15–18:21 backup `~/ninja-backups/ninja-pre-0.132.0-20261029T181502.dump` on the
  host (1,322 MB, `pg_dump` exit 0, 285 table-data entries readable).
- 18:23 release 0.132.0 (`2f050393`) pushed to `origin` and `a-m-rose`. Migrations
  `0364`–`0367` applied; `0368` aborted: "441718 findings have no state row".
  Operations restart-looped; ingest and the Jobs worker waited for contract 4 and
  admitted no work, as designed.
- Cause: the check required a state row for every finding; production has 441,718
  closed entity findings older than `finding_state`. Zero active findings lacked
  state. All other `0368` checks were run read-only on production and passed.
- 18:36 release 0.132.1 (`f761e23f`) narrowed the check to active findings.
  `0368` applied, contract 4 published, Operations healthy at 18:38. Operations was
  unavailable 18:23–18:38 (~15 minutes).
- Post-cutover the `platform-health-evaluate` Job failed: "could not determine data
  type of parameter $2". The shared admin upsert (`INSERT ... SELECT`) had untyped
  parameters. Each run rolled back; no data changed.
- 18:42 release 0.132.2 (`3b456c86`) cast every parameter (checked first with a
  prepared statement on a tiny throwaway database). Ingest and the Jobs worker were
  recreated with the fix.

## Verification

- Contract 4; Operations, ingest, Jobs worker and Postgres healthy.
- Active findings per namespace and type: all 52 counts identical to pre-window.
- `0368` assertions hold: admin view equals the retained legacy rows, no active
  finding without state, assessments/participants match their finding namespace and
  tenant, no duplicate active key per namespace, cover rules match `covered_by`.
- After the fix, `patches`, `ninja-enrichment`, `source-refresh` and the software
  queue completed; no trigger rejection ("guard must be held") or contract error in
  ingest or Jobs worker logs.
- First production `platform-evaluate` under the exclusive guard completed
  22:52–23:17 UTC (~24 minutes) without error.
- `platform-health-evaluate` still failed on 0.132.2 at
  `_eval_jobs_unmet_dependencies`: two untyped parameters inside
  `jsonb_build_object` (a path that runs only when a dependency has an active
  upstream failure). 0.132.3 (`ac12e064`) casts them; a scan found no other
  untyped parameter inside a JSON builder in ingest.
- On 0.132.3 `platform-health-evaluate` completed (23:39–23:41 UTC); 206 of 530
  active admin findings were refreshed through the common ledger; no parameter,
  guard or contract errors in the following 40 minutes. The 0.132.3 redeploy
  interrupted one evaluator run (stalled, then re-queued and running).
- Unrelated pre-existing error seen in the Jobs worker log: the shadow generic
  relationship projection (`ingest/derived.py`) logs "relationship source
  cardinality would be exceeded" and continues; R2 did not change it.

## Follow-up

- Lessons recorded: run migration abort checks read-only on production before
  release; cast parameters in `INSERT ... SELECT`.
- Local `master` in the main folder is behind `origin` (`93a2dd0` vs `3b456c86`)
  because the main folder holds uncommitted work in files R2 also changed; integrate
  when that work is committed or set aside.
- Keep the backup until R3 starts, then remove it with approval.

## Follow-up release 0.133.1 (2026-10-30)

- R2 never added the entity-only reader adapter (WP5). From 0.132.0, readers that
  query `findings` directly counted admin rows: home counts, client-page severity and
  new-issue counts, and the condition coverage summary (which listed admin rows twice).
  Notifications were not affected, because they join entity assessments.
- 0.133.1 (`d3b988e7`) makes `Finding.objects` entity-only and filters the raw SQL
  readers. Migration `0369` changes model state only.
- Verified read-only after the deploy: `0369` applied; Operations, ingest and the Jobs
  worker healthy; active findings are 39,412 entity and 555 admin; no errors in the
  Operations log.
