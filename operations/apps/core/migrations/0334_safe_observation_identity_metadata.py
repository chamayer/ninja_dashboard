"""Add the UI's safe identity scalars to the existing observation metadata view."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE VIEW operations.v_entity_observation_admin_metadata
WITH (security_barrier = true) AS
SELECT observation.observation_id, observation.tenant_id,
       observation.source_binding_id, observation.source_instance_id,
       observation.client_id, observation.device_id,
       observation.entity_type, observation.entity_key,
       observation.external_namespace, observation.parent_external_namespace,
       observation.parent_external_id, observation.external_id,
       observation.platform, observation.subplatform,
       observation.observed_at, observation.last_seen_at,
       observation.last_received_at, observation.active,
       observation.withdrawn_at,
       observation.canonical_data->>'hostname' AS canonical_hostname,
       observation.canonical_data->>'platform_group_id' AS platform_group_id,
       coalesce(nullif(observation.canonical_data->>'hostname', ''),
                observation.canonical_data->>'guest_name') AS reported_name,
       observation.canonical_data->>'serial_number' AS canonical_serial,
       observation.canonical_data->>'vm_uuid' AS vm_uuid,
       observation.canonical_data->>'link_verdict' AS link_verdict,
       coalesce((observation.canonical_data->>'archived')::boolean, false) AS archived,
       CASE WHEN observation.platform = 'Hudu'
                 AND observation.entity_type = 'cmdb.asset'
            THEN observation.raw_data->>'company_id' END AS hudu_company_id
  FROM operations.entity_observation_current observation
 WHERE observation.tenant_id = operations.current_tenant_id();

ALTER VIEW operations.v_entity_observation_admin_metadata
    OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_entity_observation_admin_metadata
    FROM PUBLIC, operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON operations.v_entity_observation_admin_metadata
    TO operations_app, operations_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_entity_observation_admin_metadata
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0333_requirement_applicability"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
