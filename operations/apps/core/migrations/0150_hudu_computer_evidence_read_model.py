"""Restrict Hudu computer evidence before expanding relayed cards."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


VIEW_SQL = """
CREATE VIEW operations.v_hudu_computer_inventory_evidence_current
WITH (security_barrier = true) AS
WITH hudu_observation AS MATERIALIZED (
    SELECT observation.observation_id, observation.tenant_id, observation.client_id,
           observation.device_id, observation.canonical_data
      FROM operations.entity_observation_current observation
     WHERE observation.tenant_id = operations.current_tenant_id()
       AND observation.active
       AND observation.entity_type = 'cmdb.asset'
       AND observation.platform = 'Hudu'
       AND (
           observation.device_id IS NOT NULL
           OR NULLIF(COALESCE(observation.canonical_data->>'source_layout',
                              observation.canonical_data->>'hudu_layout'), '')
              = ANY(ARRAY['Computer Assets', 'Servers'])
       )
)
SELECT observation.observation_id, observation.tenant_id, observation.client_id,
       observation.device_id,
       NULLIF(observation.canonical_data->>'hostname', '') AS hostname,
       NULLIF(COALESCE(observation.canonical_data->>'source_layout',
                       observation.canonical_data->>'hudu_layout'), '') AS source_layout,
       NULLIF(COALESCE(observation.canonical_data->>'source_url',
                       observation.canonical_data->>'hudu_url'), '') AS source_url,
       NULLIF(COALESCE(observation.canonical_data->>'source_serial_number',
                       observation.canonical_data->>'serial_number'), '') AS serial_number,
       NULLIF(observation.canonical_data->>'link_verdict', '') AS link_verdict,
       NULLIF(card.value->>'source', '') AS card_source,
       NULLIF(card.value->>'key', '') AS card_id,
       NULLIF(card.value->>'resolved_device_id', '') AS card_resolved_device_id,
       CASE LOWER(COALESCE(observation.canonical_data->>'archived', 'false'))
           WHEN 'true' THEN TRUE ELSE FALSE END AS is_archived
  FROM hudu_observation observation
  LEFT JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(observation.canonical_data->'relayed') = 'array'
           THEN observation.canonical_data->'relayed' ELSE '[]'::jsonb END
  ) AS card(value) ON TRUE;
"""

SECURITY_SQL = """
ALTER VIEW operations.v_hudu_computer_inventory_evidence_current
    OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_hudu_computer_inventory_evidence_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_hudu_computer_inventory_evidence_current
TO operations_app, operations_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_hudu_computer_inventory_evidence_current
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0149_hudu_computer_no_link_read_model")]

    operations: ClassVar = [
        migrations.RunSQL(
            VIEW_SQL,
            "DROP VIEW IF EXISTS operations.v_hudu_computer_inventory_evidence_current;",
        ),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
    ]
