"""Expose safe current device-observation metadata to Operations pages."""

from django.db import migrations


SQL = """
CREATE OR REPLACE VIEW operations.v_device_observation_current
WITH (security_barrier = true) AS
SELECT observation.observation_id,
       observation.tenant_id,
       observation.device_id,
       observation.source_instance_id,
       source.name AS source_name,
       observation.platform,
       observation.entity_type,
       observation.external_id,
       observation.active AS observation_active,
       observation.observed_at,
       observation.last_seen_at AS observation_last_seen_at
  FROM operations.entity_observation_current observation
  JOIN operations.source_instances source_instance
    ON source_instance.tenant_id = observation.tenant_id
   AND source_instance.id = observation.source_instance_id
  JOIN operations.sources source ON source.id = source_instance.source_id
 WHERE observation.tenant_id = operations.current_tenant_id()
   AND observation.device_id IS NOT NULL;

ALTER VIEW operations.v_device_observation_current OWNER TO operations_view_owner;
GRANT SELECT ON operations.v_device_observation_current
    TO operations_app, operations_readonly;
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0151_mac_address_visibility")]

    operations = [
        migrations.RunSQL(
            SQL,
            "DROP VIEW IF EXISTS operations.v_device_observation_current",
        )
    ]
