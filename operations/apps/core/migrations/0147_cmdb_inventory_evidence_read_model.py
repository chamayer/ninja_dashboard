"""Expose current CMDB inventory evidence for Inventory asset-class readers.

Inventory is organized by assets, not by sources. This bounded read model
exposes current CMDB evidence -- including records with no canonical-device
attachment -- for Inventory pages to classify by asset class. Computers is the
first consumer; future server, printer, network, and other asset pages reuse
the same relation. It exposes only the fields needed for inventory display and
source-card context, never raw source payloads or credentials.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations


VIEW_SQL = """
CREATE VIEW operations.v_cmdb_inventory_evidence_current
WITH (security_barrier = true) AS
SELECT observation.observation_id,
       observation.tenant_id,
       observation.client_id,
       observation.device_id,
       observation.platform AS source_name,
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
       NULLIF(card.value->>'resolved_device_id', '') AS card_resolved_device_id
  FROM operations.entity_observation_current observation
  LEFT JOIN LATERAL jsonb_array_elements(
      CASE
          WHEN jsonb_typeof(observation.canonical_data->'relayed') = 'array'
          THEN observation.canonical_data->'relayed'
          ELSE '[]'::jsonb
      END
  ) AS card(value) ON TRUE
 WHERE observation.tenant_id = operations.current_tenant_id()
   AND observation.active
   AND observation.entity_type = 'cmdb.asset';
"""

SECURITY_SQL = """
ALTER VIEW operations.v_cmdb_inventory_evidence_current
    OWNER TO operations_view_owner;

REVOKE ALL ON operations.v_cmdb_inventory_evidence_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT SELECT ON operations.v_cmdb_inventory_evidence_current
TO operations_app, operations_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_cmdb_inventory_evidence_current
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""

ASSERT_SQL = """
DO $$
DECLARE
    writable integer;
BEGIN
    SELECT count(*) INTO writable
      FROM information_schema.role_table_grants
     WHERE table_schema = 'operations'
       AND table_name = 'v_cmdb_inventory_evidence_current'
       AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
       AND grantee IN ('operations_app', 'ninja_ingest',
                       'operations_readonly', 'metabase_ro');
    IF writable > 0 THEN
        RAISE EXCEPTION 'read model retains % write grant(s); see migration 0122', writable;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0146_hudu_device_links_read_model"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            VIEW_SQL,
            "DROP VIEW IF EXISTS operations.v_cmdb_inventory_evidence_current;",
        ),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(ASSERT_SQL, migrations.RunSQL.noop),
    ]
