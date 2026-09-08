"""Operator-managed automatic Computer identity matching policy."""

from __future__ import annotations

import uuid
from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models

FORWARD_SQL = r"""
ALTER TABLE operations.identity_match_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.identity_match_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.identity_match_policies
    USING (tenant_id = operations.current_tenant_id())
    WITH CHECK (tenant_id = operations.current_tenant_id());

ALTER TABLE operations.identity_match_policies
    ADD CONSTRAINT ck_identity_match_policy_matcher
    CHECK (matcher IN ('source_identity', 'serial', 'vm_uuid', 'hostname_mac', 'hostname')),
    ADD CONSTRAINT ck_identity_match_policy_blockers
    CHECK (jsonb_typeof(blocking_signal_keys) = 'array'
           AND blocking_signal_keys <@ '["vm_uuid"]'::jsonb);

REVOKE ALL ON operations.identity_match_policies
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE ON operations.identity_match_policies TO operations_app;
GRANT SELECT ON operations.identity_match_policies
TO ninja_ingest, operations_readonly, operations_view_owner;

INSERT INTO operations.identity_match_policies (
    id, version, tenant_id, matcher, display_name, description, priority,
    requires_client_scope, requires_unique_candidate,
    avoid_same_stream_duplicates, blocking_signal_keys, confidence, enabled, reason
)
SELECT gen_random_uuid(), 1, tenant.id, rule.matcher, rule.display_name,
       rule.description, rule.priority, rule.requires_client_scope,
       TRUE, rule.avoid_same_stream_duplicates, rule.blocking_signal_keys,
       rule.confidence, TRUE, 'Seeded from the pre-policy automatic identity behavior.'
  FROM operations.tenants tenant
 CROSS JOIN (
    VALUES
      ('source_identity', 'Same source record',
       'Keep a live source record attached to its existing Computer.',
       10, FALSE, FALSE, '[]'::jsonb, 1.000::numeric),
      ('serial', 'Matching serial number',
       'Attach when one Computer for the same client has the same usable serial number.',
       20, TRUE, FALSE, '[]'::jsonb, 1.000::numeric),
      ('vm_uuid', 'Matching VM UUID',
       'Attach when one Computer for the same client has the same VM UUID.',
       30, TRUE, FALSE, '[]'::jsonb, 1.000::numeric),
      ('hostname_mac', 'Matching name and MAC address',
       'Attach when one same-client Computer has the same name and a shared MAC address; a conflicting VM UUID blocks the match.',
       40, TRUE, FALSE, '["vm_uuid"]'::jsonb, 0.990::numeric),
      ('hostname', 'Matching name',
       'Attach only to one same-client Computer with the same name; another record from the same source stream or a conflicting VM UUID blocks the match.',
       50, TRUE, TRUE, '["vm_uuid"]'::jsonb, 0.700::numeric)
 ) AS rule(
    matcher, display_name, description, priority, requires_client_scope,
    avoid_same_stream_duplicates, blocking_signal_keys, confidence
 )
ON CONFLICT (tenant_id, matcher) DO NOTHING;
"""


REVERSE_SQL = r"""
DROP POLICY IF EXISTS tenant_isolation ON operations.identity_match_policies;
DROP TABLE IF EXISTS operations.identity_match_policies;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0153_os_installation_entities"),
    ]

    operations: ClassVar[list] = [
        migrations.CreateModel(
            name="IdentityMatchPolicy",
            fields=[
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "matcher",
                    models.CharField(
                        choices=[
                            ("source_identity", "Source record identity"),
                            ("serial", "Matching serial number"),
                            ("vm_uuid", "Matching VM UUID"),
                            ("hostname_mac", "Matching name and MAC address"),
                            ("hostname", "Matching name"),
                        ],
                        max_length=32,
                    ),
                ),
                ("display_name", models.CharField(max_length=120)),
                ("description", models.CharField(blank=True, default="", max_length=300)),
                ("priority", models.PositiveSmallIntegerField()),
                ("requires_client_scope", models.BooleanField(default=True)),
                ("requires_unique_candidate", models.BooleanField(default=True)),
                ("avoid_same_stream_duplicates", models.BooleanField(default=False)),
                ("blocking_signal_keys", models.JSONField(blank=True, default=list)),
                ("confidence", models.DecimalField(decimal_places=3, max_digits=4)),
                ("enabled", models.BooleanField(default=True)),
                ("reason", models.CharField(blank=True, default="", max_length=160)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="operations.tenant"
                    ),
                ),
            ],
            options={
                "db_table": "identity_match_policies",
                "ordering": ("tenant", "priority", "matcher"),
            },
        ),
        migrations.AddConstraint(
            model_name="identitymatchpolicy",
            constraint=models.UniqueConstraint(
                fields=("tenant", "matcher"), name="uq_identity_match_policy"
            ),
        ),
        migrations.AddConstraint(
            model_name="identitymatchpolicy",
            constraint=models.UniqueConstraint(
                fields=("tenant", "priority"), name="uq_identity_match_policy_priority"
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
