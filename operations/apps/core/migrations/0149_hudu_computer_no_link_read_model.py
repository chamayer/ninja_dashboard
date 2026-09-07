"""Provide a compact Hudu-computer read model for no-link inventory filters."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


VIEW_SQL = """
CREATE VIEW operations.v_hudu_computer_inventory_observation_current
WITH (security_barrier = true) AS
SELECT observation.observation_id,
       observation.tenant_id,
       observation.client_id,
       observation.device_id,
       NULLIF(observation.canonical_data->>'hostname', '') AS hostname,
       NULLIF(COALESCE(observation.canonical_data->>'source_layout',
                       observation.canonical_data->>'hudu_layout'), '') AS source_layout,
       NULLIF(COALESCE(observation.canonical_data->>'source_url',
                       observation.canonical_data->>'hudu_url'), '') AS source_url,
       NULLIF(COALESCE(observation.canonical_data->>'source_serial_number',
                       observation.canonical_data->>'serial_number'), '') AS serial_number,
       NULLIF(observation.canonical_data->>'link_verdict', '') AS link_verdict,
       CASE LOWER(COALESCE(observation.canonical_data->>'archived', 'false'))
           WHEN 'true' THEN TRUE
           ELSE FALSE
       END AS is_archived,
       EXISTS (
           SELECT 1
           FROM jsonb_array_elements(
               CASE
                   WHEN jsonb_typeof(observation.canonical_data->'relayed') = 'array'
                   THEN observation.canonical_data->'relayed'
                   ELSE '[]'::jsonb
               END
           ) AS card(value)
           WHERE NULLIF(card.value->>'source', '') IS NOT NULL
             AND NULLIF(card.value->>'key', '') IS NOT NULL
       ) AS has_relayed_cards
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
   );
"""

SECURITY_SQL = """
ALTER VIEW operations.v_hudu_computer_inventory_observation_current
    OWNER TO operations_view_owner;

REVOKE ALL ON operations.v_hudu_computer_inventory_observation_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT SELECT ON operations.v_hudu_computer_inventory_observation_current
TO operations_app, operations_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_hudu_computer_inventory_observation_current
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0148_cmdb_inventory_evidence_archive_state"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            VIEW_SQL,
            "DROP VIEW IF EXISTS operations.v_hudu_computer_inventory_observation_current;",
        ),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
    ]
