"""Register the reviewed recovery authorities required by Software Jobs startup."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (1, 'software-catalog', 'replay_safe',
     'Replays existing local catalog/lifecycle projectors and matching before classification; no source API or external mutation is invoked.'),
    (1, 'software-overview', 'replay_safe',
     'Overview publication reads local inputs and atomically replaces one derived aggregate row. A failed SQL statement retains the prior row; replay rebuilds current results and has no external mutation.')
ON CONFLICT (tenant_id, definition_key) DO UPDATE
   SET recovery_mode = EXCLUDED.recovery_mode,
       evidence_summary = EXCLUDED.evidence_summary,
       reviewed_at = now();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0410_software_overview_protected_read"),
    ]
    # Retain audited authorities for existing snapshots on reversal, following
    # the existing Jobs recovery migrations. No unrelated policy is changed.
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
