"""Give the Ninja enrichment Job's domain lock a capacity policy.

The registry declares ``tenant:{tenant_id}:ninja-enrichment`` for
``ninja-enrichment`` but no limit row existed, so the dispatcher raised
"Jobs resource policy is unavailable" on the first queued run and the jobs
worker exited on every start. The lock matches its sibling source locks:
capacity 1, ``domain_lock`` and the policy revision 0247 gave them.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_resource_template_check;
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
            'tenant:{tenant_id}:platform-health', 'tenant:{tenant_id}:reporting'
        )
    );
INSERT INTO operations.job_resource_limits
    (resource_template, capacity, policy_revision, policy_kind)
VALUES ('tenant:{tenant_id}:ninja-enrichment', 1,
        'de77eb8a53b5c78e0f4c629906e7e0f91d6af6618b85a5114f0fd98b243920af', 'domain_lock')
ON CONFLICT (resource_template) DO UPDATE SET
    capacity = EXCLUDED.capacity, policy_revision = EXCLUDED.policy_revision,
    policy_kind = EXCLUDED.policy_kind;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0335_ninja_enrichment_replay_safe_recovery"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
