"""Migration 0128 -- expose a candidate's source layout without its payload.

`promote_asset_candidates` needs to scope promotion by source layout, because
the 4,843 unlinked CMDB candidates span 20 layouts holding real hardware,
locations, software, client attributes and one relationship type. Promoting
them wholesale would make `asset` a catch-all for four other classes.

The layout lives in `entity_observation_current.canonical_data`, which
`operations_app` cannot read: migration 0117 revoked raw and canonical
observation columns from every runtime role to close an evidence-exposure path.
That revoke is correct and stays. Reading the payload back to obtain one
classification field would undo a shipped security control to save a join.

So this is the narrow read model instead: **candidate id, entity class, status
and layout name -- nothing else**. No hostname, no serial, no URL, no card
contents, no `canonical_data` passthrough. A layout name is a Hudu
configuration label ("Servers", "Printing"), not evidence about a customer
asset, which is why it can cross the boundary the payload cannot.

Follows the E5.1 pattern exactly: `security_barrier`, owned by
`operations_view_owner` (no login, no BYPASSRLS) so the underlying revoke is
not bypassed by the view's own privileges, and DML explicitly revoked from
every runtime role per `operations/AGENTS.md` -- `ALTER DEFAULT PRIVILEGES`
grants `operations_app` full DML on everything `operations_migrate` creates,
and PostgreSQL has no default-privilege object type separating views from
tables.

Tenant-scoped through `operations.current_tenant_id()`, consistent with the
other admin read models, so RLS is not weakened by the definer's ownership.
"""

from typing import ClassVar

from django.db import migrations

VIEW_SQL = """
CREATE OR REPLACE VIEW operations.v_entity_candidate_source_layout
WITH (security_barrier = true) AS
SELECT candidate.id AS candidate_id,
       candidate.tenant_id,
       candidate.proposed_entity_class_id AS entity_class,
       candidate.status,
       candidate.client_id,
       observation.canonical_data->>'hudu_layout' AS source_layout
  FROM operations.entity_candidates candidate
  JOIN operations.entity_observation_current observation
    ON observation.tenant_id = candidate.tenant_id
   AND observation.source_instance_id = candidate.source_instance_id
   AND observation.external_namespace = candidate.external_namespace
   AND observation.external_id = candidate.external_id
 WHERE candidate.tenant_id = operations.current_tenant_id()
   AND observation.active;
"""

SECURITY_SQL = """
ALTER VIEW operations.v_entity_candidate_source_layout
    OWNER TO operations_view_owner;

REVOKE ALL ON operations.v_entity_candidate_source_layout
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;

GRANT SELECT ON operations.v_entity_candidate_source_layout
TO operations_app, operations_readonly;
"""

ASSERT_SQL = """
DO $$
DECLARE
    writable integer;
BEGIN
    SELECT count(*) INTO writable
      FROM information_schema.role_table_grants
     WHERE table_schema = 'operations'
       AND table_name = 'v_entity_candidate_source_layout'
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

DROP_SQL = "DROP VIEW IF EXISTS operations.v_entity_candidate_source_layout;"


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0127_split_trust_out_of_software_categories"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(VIEW_SQL, DROP_SQL),
        migrations.RunSQL(SECURITY_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(ASSERT_SQL, migrations.RunSQL.noop),
    ]
