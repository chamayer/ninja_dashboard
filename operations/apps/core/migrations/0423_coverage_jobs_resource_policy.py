"""Register Coverage's domain lock so queued work cannot abort dispatch."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT job_resource_limits_resource_template_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_resource_template_check CHECK (
        resource_template IN (
            'execution:deployment', 'execution:emergency-child',
            'capacity:external-io', 'capacity:processing', 'capacity:control',
            'tenant:{tenant_id}:state', 'global:intel-cve-corpus',
            'global:software-catalog', 'tenant:{tenant_id}:software-inventory',
            'tenant:{tenant_id}:software-findings', 'tenant:{tenant_id}:notification-delivery',
            'tenant:{tenant_id}:legacy-agent-compliance', 'tenant:{tenant_id}:ninja-source',
            'tenant:{tenant_id}:ninja-enrichment',
            'tenant:{tenant_id}:agent-sources', 'tenant:{tenant_id}:documentation-source',
            'tenant:{tenant_id}:source-binding:{scope_identity}',
            'tenant:{tenant_id}:software-state', 'tenant:{tenant_id}:patch-state',
            'tenant:{tenant_id}:platform-findings', 'tenant:{tenant_id}:cmdb-findings',
            'tenant:{tenant_id}:identity-state', 'tenant:{tenant_id}:parity-state',
            'tenant:{tenant_id}:software-cve-match', 'tenant:{tenant_id}:threat-intelligence',
            'tenant:{tenant_id}:history-retention', 'tenant:{tenant_id}:source-actions',
            'tenant:{tenant_id}:source-demand', 'tenant:{tenant_id}:run-history',
            'tenant:{tenant_id}:platform-health', 'tenant:{tenant_id}:reporting',
            'tenant:{tenant_id}:source-record-assessment',
            'tenant:{tenant_id}:coverage-read-model'
        )
    );
INSERT INTO operations.job_resource_limits
    (resource_template, capacity, policy_revision, policy_kind)
VALUES ('tenant:{tenant_id}:coverage-read-model', 1,
        'de77eb8a53b5c78e0f4c629906e7e0f91d6af6618b85a5114f0fd98b243920af', 'domain_lock')
ON CONFLICT (resource_template) DO NOTHING;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [("operations", "0422_coverage_maintained_read_model")]
    # Retain an admitted resource policy on reversal, like migrations 0336/0372.
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
