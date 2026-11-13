"""Classify each source stream once before combining its record counts."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE VIEW operations.v_source_instance_record_counts
WITH (security_barrier = true) AS
WITH streams AS MATERIALIZED (
    SELECT observation.tenant_id, observation.source_instance_id,
           observation.external_namespace, observation.entity_type,
           count(*)::bigint AS current_count,
           count(*) FILTER (WHERE observation.active)::bigint AS active_count,
           count(*) FILTER (WHERE NOT observation.active)::bigint AS withdrawn_count,
           max(observation.last_seen_at) AS last_seen_at
      FROM operations.v_entity_observation_admin_metadata observation
     WHERE observation.tenant_id = operations.current_tenant_id()
     GROUP BY observation.tenant_id, observation.source_instance_id,
              observation.external_namespace, observation.entity_type
), included AS MATERIALIZED (
    SELECT * FROM streams
     WHERE NOT operations.is_companion_stream(
         tenant_id, source_instance_id, external_namespace)
)
SELECT included.tenant_id, included.source_instance_id, included.entity_type,
       kind.entity_class_id AS entity_class,
       sum(included.current_count)::bigint AS current_count,
       sum(included.active_count)::bigint AS active_count,
       sum(included.withdrawn_count)::bigint AS withdrawn_count,
       max(included.last_seen_at) AS last_seen_at
  FROM included JOIN operations.entity_types kind ON kind.name = included.entity_type
 GROUP BY included.tenant_id, included.source_instance_id,
          included.entity_type, kind.entity_class_id;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_source_instance_record_counts
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly;
"""

_old = import_module("apps.core.migrations.0397_source_record_companions").SCHEMA_SQL
_start = _old.index("CREATE VIEW operations.v_source_instance_record_counts")
REVERSE_SQL = _old[_start:_old.index(";", _start) + 1].replace(
    "CREATE VIEW", "CREATE OR REPLACE VIEW", 1
)
REVERSE_SQL += """
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_source_instance_record_counts
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0416_keep_valid_software_summary_during_refresh"),
    ]
    # CREATE OR REPLACE retains the existing owner and ACL. Outputs and
    # tenant/security-barrier boundaries are unchanged; no new grants.
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
