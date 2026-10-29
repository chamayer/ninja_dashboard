# PLAN-003 R2 — maintenance window runbook

Release: migrations `0364`–`0368` with the converted writers (branch `plan003-r2`).
User decision, 2026-10-29: no production-copy rehearsal. Consequences accepted:
migration time on ~618,000 findings, rollback at real volume and the first evaluator
run under the exclusive tenant guard are unmeasured; the window must therefore
drain writers, keep a backup and follow the abort path below. Each production step
still needs the user's approval at the time.

## Before the window

1. Confirm `master` has not gained migrations after `0363`; otherwise rebase and
   renumber `0364`–`0368`.
2. Release commit: `VERSION` 0.132.0 and a `CHANGELOG.md` entry; run the release
   governance check on a clean worktree of the exact commit.

## Window

1. **Backup** (approval): `pg_dump -Fc` of the production database on the host,
   kept until the release is verified. Record its size and path.
2. **Drain** (approval): stop `ninja-jobs-worker` and `operations-ingest`. Confirm
   no session other than monitoring is active in the database
   (`pg_stat_activity`, `state <> 'idle'`).
3. **Push** (approval): `origin`, then `a-m-rose`. The push redeploys every service.
   Operations applies `0364`–`0368` at startup and runs `check_findings_contract`.
   The new ingest and Jobs worker wait for contract 4 and admit no work before it,
   so they cannot hold a collection transaction open against the migration.
4. **Watch** Operations logs until `Applying operations.0368... OK`, the contract
   check and Gunicorn start. If a migration waits on a lock, inspect
   `pg_stat_activity` for `Lock:` waits before changing anything.

## Verify (read-only)

- `operations.finding_contract_version()` is 4; all containers healthy.
- `admin_findings` view equals `admin_findings_legacy` (0368 already asserted it).
- Every finding has a `finding_state` row; counts of open findings per type match
  the pre-window counts taken in step 2 (record them first).
- One platform evaluator run completes; record its duration.
- Issues, Admin Health, client mappings and a Computer page load after sign-in.

## Abort and rollback

- Each Django migration commits separately. If one of `0364`–`0368` fails, earlier
  ones stay applied and the previous release cannot run on that schema (its
  upserts use the old conflict target). With ingest and the Jobs worker still
  stopped, run `python manage.py migrate operations 0363` in the new Operations
  image (all five migrations have reverse SQL), then redeploy the previous release
  (0.131.0, `302a2f2`) and start the workers.
- Reverse SQL does not restore the 8 deleted mislabelled assessment rows; they
  are derived and re-assessed by the next evaluation.
- If reverse migration fails, restore the step-1 backup (separate approval).
