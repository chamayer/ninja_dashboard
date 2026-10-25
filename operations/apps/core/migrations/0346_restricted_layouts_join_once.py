"""Check restricted layouts once per query, not once per row.

0345's per-row subquery made the planner overestimate the safe metadata view
(cost ~1M), so JIT compilation added about 0.9 s to Source records queries.
Joining ``evaluator_config`` once returns the same rows and masking
(rehearsed on production: 9 restricted, 37,179 unchanged) at the old speed.
The definition is otherwise 0345's.
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
  -- Joined once, not a per-row subquery: the per-row form looked so costly
  -- to the planner that JIT compilation added about a second to every page.
  LEFT JOIN operations.evaluator_config restriction
    ON restriction.tenant_id = observation.tenant_id
   AND restriction.evaluator_name = 'restricted_source_layouts'
  CROSS JOIN LATERAL (
      SELECT coalesce(restriction.config->'layouts'
                      ? coalesce(observation.canonical_data->>'source_layout',
                                 observation.canonical_data->>'hudu_layout'),
                      false) AS is_restricted) restricted
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
        ("operations", "0345_restricted_source_layouts"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
