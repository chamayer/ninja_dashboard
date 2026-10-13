"""Expose the selected device last-user value to its existing consumer.

User exposure previously reconstructed a device-to-Ninja mapping at request
time, then read Ninja's compatibility observation view.  ``last_user`` is
already a selected effective device attribute, so that reconstruction repeated
identity work and bypassed the normal attribute authority boundary.

This view is deliberately a read surface, not a new store or projection.  It
contains only the selected effective value, its device, and when that value was
projected.  The effective-attribute projector remains its sole writer and
authority.  ``last_user`` is sensitive, so raw values remain unavailable via
the generic effective-attribute evidence view; this narrow view is granted
only to the existing Operations application role that already presents User
exposure to authenticated operators.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE VIEW operations.v_device_last_user_current
WITH (security_barrier = true, security_invoker = false) AS
SELECT effective.tenant_id,
       device.id AS device_id,
       btrim(effective.value_text) AS last_user,
       effective.projected_at
FROM operations.entity_attribute_effective_current effective
JOIN operations.attribute_definitions definition
  ON definition.id = effective.attribute_definition_id
JOIN operations.devices device
  ON device.tenant_id = effective.tenant_id
 AND device.entity_id = effective.entity_id
 AND device.deleted_at IS NULL
WHERE effective.tenant_id = operations.current_tenant_id()
  AND definition.key = 'last_user'
  AND effective.status = 'selected'
  AND effective.value_text IS NOT NULL
  AND btrim(effective.value_text) <> '';

ALTER VIEW operations.v_device_last_user_current
    OWNER TO operations_view_owner;

REVOKE ALL ON operations.v_device_last_user_current FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_device_last_user_current
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON operations.v_device_last_user_current TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0289_retire_ninja_source_link_numeric_lookup"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            reverse_sql="DROP VIEW IF EXISTS operations.v_device_last_user_current;",
        ),
    ]
