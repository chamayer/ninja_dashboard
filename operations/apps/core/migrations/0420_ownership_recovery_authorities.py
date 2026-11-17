"""Allow existing governed recovery to replay interrupted ownership inputs."""

from django.db import migrations


FORWARD_SQL = """
INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (1, 'computer-client-ownership', 'replay_safe',
     'Changed Computer ownership reconciliation reads local evidence and projects each Computer atomically. Dirty inputs are drained without external mutation; replay converges to current ownership.'),
    (1, 'computer-client-ownership-sweep', 'replay_safe',
     'The ownership sweep pages local Computers and projects each atomically, then drains dirty inputs. Replay converges to current ownership and has no external mutation.')
ON CONFLICT (tenant_id, definition_key) DO UPDATE
   SET recovery_mode = EXCLUDED.recovery_mode,
       evidence_summary = EXCLUDED.evidence_summary,
       reviewed_at = now();
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0419_coverage_record_counts")]
    # Retain audited recovery evidence on rollback, as other authority migrations do.
    operations = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
