"""Restrict sensitive Hudu layouts: collected, never shown (ADR-0044 decision 3).

* ``evaluator_config`` row ``restricted_source_layouts``: the layouts whose
  records keep being collected but whose name, serial, VM UUID and source link
  the safe metadata view returns as NULL. Seeded with "Credit Card"; admins
  edit the list.
* ``v_entity_observation_admin_metadata`` appends ``restricted``; the
  definition is otherwise 0344's. Raw and canonical payloads stay restricted
  (0117).
"""

from __future__ import annotations

import json
from typing import ClassVar

from django.db import migrations

SETTINGS = {"layouts": ["Credit Card"]}

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
       CASE WHEN NOT restricted.is_restricted THEN observation.canonical_data->>'hostname' END AS canonical_hostname,
       observation.canonical_data->>'platform_group_id' AS platform_group_id,
       CASE WHEN NOT restricted.is_restricted
            THEN coalesce(nullif(observation.canonical_data->>'hostname', ''),
                          observation.canonical_data->>'guest_name') END AS reported_name,
       CASE WHEN NOT restricted.is_restricted THEN observation.canonical_data->>'serial_number' END AS canonical_serial,
       CASE WHEN NOT restricted.is_restricted THEN observation.canonical_data->>'vm_uuid' END AS vm_uuid,
       observation.canonical_data->>'link_verdict' AS link_verdict,
       coalesce((observation.canonical_data->>'archived')::boolean, false) AS archived,
       CASE WHEN observation.platform = 'Hudu'
                 AND observation.entity_type = 'cmdb.asset'
            THEN observation.raw_data->>'company_id' END AS hudu_company_id,
       -- Only a JSON array is a monitor list; anything else is left out, so
       -- one malformed value cannot break every reader of the view.
       CASE WHEN jsonb_typeof(observation.canonical_data->'process_monitors') = 'array'
            THEN observation.canonical_data->'process_monitors' END AS process_monitors,
       -- What kind of record this is in its source and where it lives there
       -- (Hudu layout and asset URL), for Inventory > Source records.
       nullif(coalesce(observation.canonical_data->>'source_layout',
                       observation.canonical_data->>'hudu_layout'), '') AS source_layout,
       CASE WHEN NOT restricted.is_restricted THEN nullif(observation.canonical_data->>'hudu_url', '') END AS source_url,
       -- A restricted layout (ADR-0044 decision 3) stays collected; its name,
       -- serial and links are never shown.
       restricted.is_restricted AS restricted
  FROM operations.entity_observation_current observation
  CROSS JOIN LATERAL (SELECT EXISTS (SELECT 1 FROM operations.evaluator_config restriction
                     WHERE restriction.tenant_id = observation.tenant_id
                       AND restriction.evaluator_name = 'restricted_source_layouts'
                       AND restriction.config->'layouts' ? coalesce(observation.canonical_data->>'source_layout',
                                                                    observation.canonical_data->>'hudu_layout')) AS is_restricted) restricted
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


def seed(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operations.evaluator_config
                (id, tenant_id, evaluator_name, config, updated_at)
            VALUES (gen_random_uuid(), 1, 'restricted_source_layouts', %s::jsonb, now())
            ON CONFLICT (tenant_id, evaluator_name) DO NOTHING
            """,
            (json.dumps(SETTINGS),),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0344_source_record_layout_and_url"),
    ]

    operations: ClassVar[list] = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
