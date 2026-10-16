"""Hudu documentation is a coverage requirement (ADR-0032, user decision 2026-10-16).

Adds Hudu to the requirement catalog (``agents``) and a Hudu ``cmdb.asset``
requirement for every Computer: one row in each requirement profile and one
global row for clients without a profile. Rows are data; an administrator
can change or disable them per profile or client like any other
requirement. A Computer whose every current Hudu asset is archived does not
satisfy it (``ingest.evaluator._PRESENCE_SATISFIES``). Measured 2026-10-16:
423 Computers with agents have no current Hudu asset.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'coverage_requirement.hudu_documentation',
    'ADR-0032: every Computer is documented in Hudu; an archived asset does not count.',
    '{"migration": "0312_hudu_documentation_required"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0312', NULL, true);

INSERT INTO operations.agents
    (id, name, entity_type, supported_os_groups, default_severity, default_gap_after_hours,
     default_confidence_probable, default_confidence_confirmed)
SELECT coalesce(max(id), 0) + 1, 'Hudu', 'cmdb.asset',
       '["Windows", "macOS", "Linux", "Other", "Unknown"]'::jsonb, 'medium', 720, 1440, 2160
  FROM operations.agents
HAVING NOT EXISTS (SELECT 1 FROM operations.agents WHERE name = 'Hudu');

INSERT INTO operations.requirement_profile_items
    (version, id, entity_type, platform, device_scope, severity, gap_after_hours,
     confidence_probable, confidence_confirmed, profile_id, tenant_id, agent_id,
     applicable_os_groups)
SELECT 1, gen_random_uuid(), 'cmdb.asset', 'Hudu', 'all', 'medium', 720, 1440, 2160,
       p.id, p.tenant_id, (SELECT id FROM operations.agents WHERE name = 'Hudu'), NULL
  FROM operations.requirement_profiles p
ON CONFLICT (tenant_id, profile_id, entity_type, platform, device_scope) DO NOTHING;

INSERT INTO operations.coverage_requirements
    (version, id, entity_type, platform, device_scope, severity, gap_after_hours,
     confidence_probable, confidence_confirmed, enabled, created_at, client_id, tenant_id,
     agent_id, applicable_os_groups)
SELECT 1, gen_random_uuid(), 'cmdb.asset', 'Hudu', 'all', 'medium', 720, 1440, 2160, TRUE,
       now(), NULL, t.tenant_id, (SELECT id FROM operations.agents WHERE name = 'Hudu'), NULL
  FROM (SELECT DISTINCT tenant_id FROM operations.coverage_requirements
         WHERE client_id IS NULL) t
 WHERE NOT EXISTS (
     SELECT 1 FROM operations.coverage_requirements c
      WHERE c.tenant_id = t.tenant_id AND c.client_id IS NULL
        AND c.entity_type = 'cmdb.asset' AND c.platform = 'Hudu');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0311_confirmed_in_use"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
