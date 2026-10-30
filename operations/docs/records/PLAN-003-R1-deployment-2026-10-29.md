# PLAN-003 R1 — 0.131.0 deployment

Date: 2026-10-29. The user approved the push including automatic deployment and
migrations `0362`–`0363`, then read-only verification and, during the incident
below, a brief stop of ingest and the Jobs worker.

- Commits: R1 `da16167`, release `302a2f2` (0.131.0). The release check passed on
  a clean worktree of `302a2f2`. Pushed to `origin`, then `a-m-rose`; both report
  `302a2f2`. Per `AGENTS.md`, no separate redeploy was triggered.
- Outgoing ancestry also included the local development stack (`1176034`) and the
  user's search fixes (`a714491`, `d3028af`, `f08b604`).

## Incident: Operations down about 11 minutes

Operations started at 15:38 EDT and stayed unhealthy while `0362`
(`CREATE UNIQUE INDEX CONCURRENTLY`) waited on `virtualxid`. A concurrent build
waits for all older transactions, and ingest's Ninja collection holds an open
transaction on its cycle-lock connection for the whole cycle (`ingest/main.py:90`,
"idle in transaction"). With approval, `ninja-jobs-worker` and `operations-ingest`
were stopped; `0362` applied at 19:49:10 UTC and `0363` at 19:49:13 UTC, and
Operations was healthy at 15:49 EDT. Both workers were started again and are
healthy. Stopped transactions rolled back; the interrupted collection retries on
its next cycle.

Lesson: a concurrent index build in an Operations startup migration can wait for
a whole ingest collection cycle. For a table this size a normal index build
(seconds of blocked writes) is the better choice, or the release must drain ingest.

## Verification (read-only)

- Containers: Operations, ingest, Jobs worker and Postgres healthy.
- `operations.django_migrations` records `0362` and `0363`; `uq_findings_tenant_id`
  is valid; the four tenant-guard functions exist.
- Not verified: authenticated browser pages, ingest cycle completion after restart.
