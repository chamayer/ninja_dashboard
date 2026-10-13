"""Approve replay-safe recovery for local-only and read-only-fetch Jobs.

Before this, only collection, evaluation and intelligence Jobs were replay-safe.
Every other Job stayed contained after a worker restart until an administrator
reviewed it, and a contained hold blocks its shared resource.  A deploy that
interrupted ``software-queue-drain`` therefore stopped software inventory until
someone released the hold.  These Jobs only read public or Ninja data and write
Operations rows in transactions or leased queue entries, so a replay converges.
Jobs with external effects (notifications, source actions, agent compliance,
retention purges) keep manual review.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (1, 'software-queue-drain', 'replay_safe', 'The software queue drain only reads Ninja inventory and writes local inventory rows. Queue entries are leased and an expired lease resets the entry to pending, so a replay converges and mutates nothing in Ninja.'),
    (1, 'software-enqueue-orgs', 'replay_safe', 'The scheduled sweep only inserts deduplicated pending queue rows for organizations already known locally. A replay adds no duplicates and has no external mutation.'),
    (1, 'software-classify', 'replay_safe', 'Combined software classification only reads public package metadata and reconciles local intelligence, findings, and read models. A later replay converges to the current installation and policy state and has no external mutation.'),
    (1, 'platform-health-evaluate', 'replay_safe', 'Platform-health evaluation reads local queue and run state and convergently updates local health findings. A later replay has no external mutation.'),
    (1, 'cmdb-evaluate', 'replay_safe', 'CMDB evaluation reads local documentation observations and convergently updates local findings. A later replay has no external mutation.'),
    (1, 'run-log-recovery', 'replay_safe', 'Diagnostic recovery only closes stale local run-log rows. A later replay finds nothing further to close and has no external mutation.'),
    (1, 'parity-check', 'replay_safe', 'The parity check reads local state and rewrites local parity and run-log records. A later replay converges and has no external mutation.'),
    (1, 'intel-winget', 'replay_safe', 'The Windows package refresh only reads public package metadata and performs transaction-scoped upserts of local safety signals. A later replay converges to current feed state and has no external mutation.'),
    (1, 'intel-chocolatey', 'replay_safe', 'The Chocolatey refresh only reads public package metadata and performs transaction-scoped upserts of local safety signals. A later replay converges to current feed state and has no external mutation.'),
    (1, 'intel-capability', 'replay_safe', 'Capability projection derives local catalog assertions from local corpus and rules in one database transaction. A later replay converges and has no external mutation.'),
    (1, 'intel-category', 'replay_safe', 'Category projection derives local catalog assertions from local corpus and rules in one database transaction. A later replay converges and has no external mutation.'),
    (1, 'intel-lolrmm', 'replay_safe', 'The remote-management catalog refresh only downloads a public archive and upserts local catalog rows in one database transaction. A later replay converges to the current archive and has no external mutation.')
ON CONFLICT (tenant_id, definition_key) DO UPDATE
   SET recovery_mode = EXCLUDED.recovery_mode,
       evidence_summary = EXCLUDED.evidence_summary,
       reviewed_at = now();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0279_jobs_dependency_accepts_merged_software_run"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
