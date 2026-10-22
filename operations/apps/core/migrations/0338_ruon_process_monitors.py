"""Show R-U-ON process monitors on their machine's source record.

R-U-ON ``ProcessOn`` agents watch a process on a machine that also runs a
``ServerOn`` agent. The collector now lists each paired monitor on the
machine's record as ``canonical_data.process_monitors`` (name, agent id,
on/off). Raw and canonical payloads stay restricted (0117), so the Computer
page reads that one list through the safe metadata view, as 0334 did for the
identity scalars. The view definition is otherwise 0334's, unchanged.
"""

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
            THEN observation.raw_data->>'company_id' END AS hudu_company_id,
       -- Only a JSON array is a monitor list; anything else is left out, so
       -- one malformed value cannot break every reader of the view.
       CASE WHEN jsonb_typeof(observation.canonical_data->'process_monitors') = 'array'
            THEN observation.canonical_data->'process_monitors' END AS process_monitors
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
        ("operations", "0337_client_candidate_renamed_status"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
