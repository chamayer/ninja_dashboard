"""Expose the safe Hudu card summary for a device-attached Hudu asset.

The Hudu connector stores the source cards in restricted observation evidence.
Coverage needs only the Hudu asset URL and each card's source and ID, not the
card payload.  This tenant-scoped read model exposes that exact projection for
assets the resolver already attached to a canonical device.  It deliberately
does not attach unresolved, stale, or divergent Hudu assets by hostname.

The view follows the established restricted-evidence read-model pattern:
``security_barrier``, owner ``operations_view_owner``, the tenant function in
the predicate, and no runtime DML grants.  The explicit revoke is required
because default privileges otherwise give ``operations_app`` view DML.
"""

from typing import ClassVar

from django.db import migrations

VIEW_SQL = """
CREATE VIEW operations.v_device_hudu_link_current
WITH (security_barrier = true) AS
SELECT observation.tenant_id,
       observation.device_id,
       NULLIF(observation.canonical_data->>'hudu_url', '') AS hudu_url,
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
   AND observation.platform = 'Hudu'
   AND observation.entity_type = 'cmdb.asset'
   AND observation.device_id IS NOT NULL;
"""

SECURITY_SQL = """
ALTER VIEW operations.v_device_hudu_link_current
    OWNER TO operations_view_owner;

REVOKE ALL ON operations.v_device_hudu_link_current
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT SELECT ON operations.v_device_hudu_link_current
TO operations_app, operations_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON operations.v_device_hudu_link_current
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
       AND table_name = 'v_device_hudu_link_current'
       AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
       AND grantee IN ('operations_app', 'ninja_ingest',
                       'operations_readonly', 'metabase_ro');
    IF writable > 0 THEN
        RAISE EXCEPTION
            'read model retains % write grant(s); see migration 0122', writable;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("operations", "0145_safe_ninja_shadow_ids"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            VIEW_SQL,
            "DROP VIEW IF EXISTS operations.v_device_hudu_link_current;",
        ),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(ASSERT_SQL, migrations.RunSQL.noop),
    ]
