"""Narrow software Jobs to publishing ownership and raise safe processing capacity."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_capacity_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_capacity_check CHECK (capacity BETWEEN 1 AND 5);

ALTER TABLE operations.job_resource_limits
    DROP CONSTRAINT IF EXISTS job_resource_limits_resource_template_check;
ALTER TABLE operations.job_resource_limits
    ADD CONSTRAINT job_resource_limits_resource_template_check CHECK (
        resource_template IN (
            'execution:deployment', 'execution:emergency-child',
            'capacity:external-io', 'capacity:processing', 'capacity:control',
            'tenant:{tenant_id}:state', 'global:intel-cve-corpus',
            'global:software-catalog', 'tenant:{tenant_id}:software-inventory',
            'tenant:{tenant_id}:software-findings',
            'tenant:{tenant_id}:notification-delivery',
            'tenant:{tenant_id}:legacy-agent-compliance',
            'tenant:{tenant_id}:ninja-source', 'tenant:{tenant_id}:agent-sources',
            'tenant:{tenant_id}:documentation-source', 'tenant:{tenant_id}:software-state',
            'tenant:{tenant_id}:patch-state', 'tenant:{tenant_id}:platform-findings',
            'tenant:{tenant_id}:cmdb-findings', 'tenant:{tenant_id}:identity-state',
            'tenant:{tenant_id}:parity-state', 'tenant:{tenant_id}:software-cve-match',
            'tenant:{tenant_id}:threat-intelligence', 'tenant:{tenant_id}:history-retention',
            'tenant:{tenant_id}:source-actions', 'tenant:{tenant_id}:source-demand',
            'tenant:{tenant_id}:run-history', 'tenant:{tenant_id}:platform-health',
            'tenant:{tenant_id}:reporting'
        )
    );

INSERT INTO operations.job_resource_limits
    (resource_template, capacity, policy_revision, policy_kind)
VALUES
    ('tenant:{tenant_id}:software-findings', 1,
     'b87269dca3cb1f74049e648cd58f3a4c57c65858c6c9ad53c1f0109a3a5045b6', 'domain_lock')
ON CONFLICT (resource_template) DO UPDATE
    SET capacity = EXCLUDED.capacity,
        policy_revision = EXCLUDED.policy_revision,
        policy_kind = EXCLUDED.policy_kind;

UPDATE operations.job_resource_limits
   SET capacity = 2,
       policy_revision = 'b87269dca3cb1f74049e648cd58f3a4c57c65858c6c9ad53c1f0109a3a5045b6'
 WHERE resource_template = 'capacity:processing'
   AND policy_kind = 'execution_pool';

UPDATE operations.job_resource_limits
   SET capacity = 5,
       policy_revision = 'b87269dca3cb1f74049e648cd58f3a4c57c65858c6c9ad53c1f0109a3a5045b6'
 WHERE resource_template = 'execution:emergency-child'
   AND policy_kind = 'execution_pool';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0261_jobs_wait_reason_truth"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
