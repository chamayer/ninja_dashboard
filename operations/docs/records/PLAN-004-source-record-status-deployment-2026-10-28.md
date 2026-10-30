# PLAN-004 — Status/contact repair deployment

The user separately approved the repair commit, 0.130.1 release-metadata commit,
and push including migration 0361 and automatic Portainer deployment.

- Repair: `a0a2c53`; release: `c7628b9`. Both remotes report full release hash
  `c7628b9fd8033e0f518b892d7696aca66f2c50bd` on master. Origin was pushed first,
  followed immediately by `a-m-rose`; no separate redeploy was triggered.
- The outgoing ancestry also included the existing documentation-only PLAN-022
  closeout (`00a6cde`) and source-instance display-title fix (`9aef8fc`).
- Portainer selected the release commit. Ingest reports 0.130.1; Operations,
  ingest and Jobs worker are healthy after replacement.
- Production recorded `0361_source_record_reported_contact` applied at
  2026-10-28 23:45:40 UTC. The new column is `timestamp with time zone`.
- Deployed reader and migration SHA-256 hashes match the release tree.
  Deployed Django system checks report no issues.
- Read-only runtime-role verification confirms metadata SELECT permitted,
  metadata DML denied, raw observation SELECT denied, and security barrier
  retained. An unrelated tenant context returns zero metadata records.
- Tenant-scoped aggregate metadata reads succeed for 5,607 present ScreenConnect
  sessions: 2,134 report Offline; 1,674 have no measurable contact timestamp.
  Missing contact is preserved, not replaced by collection time.

No manual collection, evaluation, source repair or attachment was triggered.
Authenticated browser acceptance remains unverified. The broader PLAN-004 review
remains active; this record closes only the approved status/contact repair.
