"""Expose current source-only computer records to the Operations reader."""

from django.db import migrations


SQL = """
CREATE VIEW operations.v_computer_inventory_source_record_current
WITH (security_barrier = true) AS
SELECT observation.observation_id, observation.tenant_id, observation.client_id,
       client.slug AS client_slug, client.display_name AS client_name,
       COALESCE(NULLIF(observation.canonical_data->>'hostname', ''),
                NULLIF(observation.canonical_data->>'name', ''),
                NULLIF(observation.canonical_data->>'system_name', ''),
                NULLIF(observation.canonical_data->>'dns_name', ''),
                NULLIF(observation.canonical_data->>'netbios_name', ''),
                NULLIF(observation.canonical_data->>'display_name', ''), '') AS hostname,
       observation.platform, observation.entity_type, observation.canonical_data
  FROM operations.entity_observation_current observation
  LEFT JOIN operations.devices device
    ON device.id = observation.device_id
   AND device.deleted_at IS NULL
   AND device.lifecycle_status <> 'retired'
  LEFT JOIN operations.clients client ON client.id = observation.client_id
 WHERE observation.tenant_id = operations.current_tenant_id()
   AND observation.active
   AND (observation.entity_type LIKE 'agent.%' OR observation.entity_type = 'vm.guest')
   AND device.id IS NULL;

ALTER VIEW operations.v_computer_inventory_source_record_current OWNER TO operations_view_owner;
REVOKE ALL ON operations.v_computer_inventory_source_record_current FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_computer_inventory_source_record_current TO operations_app, operations_readonly;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0154_identity_match_policies")]

    operations = [migrations.RunSQL(SQL, "DROP VIEW IF EXISTS operations.v_computer_inventory_source_record_current")]
