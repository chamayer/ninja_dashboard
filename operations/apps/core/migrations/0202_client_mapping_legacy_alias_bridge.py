"""Bridge legacy aliases and expose duplicate source-group review findings."""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar

from django.db import migrations


SOURCE_VERSION = "conditions-taxonomy-6"
NEW_VERSION = "conditions-taxonomy-7"


BRIDGE_SQL = r"""
WITH latest_org_observation AS (
    SELECT DISTINCT ON (
        observation.tenant_id,
        observation.source_instance_id,
        observation.external_namespace,
        observation.external_id
    )
           observation.tenant_id,
           observation.source_instance_id,
           observation.external_namespace,
           observation.external_id,
           observation.canonical_data ->> 'name' AS observed_name
      FROM operations.entity_observation_current observation
     WHERE observation.tenant_id = 1
       AND observation.entity_type = 'org'
       AND observation.active
     ORDER BY observation.tenant_id,
              observation.source_instance_id,
              observation.external_namespace,
              observation.external_id,
              observation.observed_at DESC
)
INSERT INTO operations.client_source_mapping_decisions
    (tenant_id, source_link_id, state, provenance, reason, decided_by_id)
SELECT link.tenant_id,
       link.id,
       CASE WHEN alias.tier IN ('manual', 'seed', 'alignment')
            THEN 'explicit' ELSE 'automatic' END,
       'legacy_alias',
       'Imported enabled ' || alias.tier || ' client name alias: ' || alias.alias,
       NULL
  FROM operations.entity_source_links link
  JOIN latest_org_observation observation
    ON observation.tenant_id = link.tenant_id
   AND observation.source_instance_id = link.source_instance_id
   AND observation.external_namespace = link.external_namespace
   AND observation.external_id = link.external_id
  JOIN operations.client_name_aliases alias
    ON alias.tenant_id = link.tenant_id
   AND alias.client_id = link.entity_id
   AND alias.enabled
   AND alias.normalized_name = regexp_replace(
       lower(coalesce(observation.observed_name, '')), '[\s\-_.]', '', 'g'
   )
 WHERE link.tenant_id = 1
   AND link.entity_class_id = 'client'
   AND observation.observed_name IS NOT NULL
ON CONFLICT (tenant_id, source_link_id) WHERE superseded_at IS NULL DO NOTHING;
"""


def seed_finding_type_and_policy(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operations.finding_types
                (name, default_severity, finding_class, source_module,
                 auto_resolvable, runbook_path, description)
            VALUES (%s, %s, %s, %s, %s, '', %s)
            ON CONFLICT (name) DO NOTHING
            """,
            [
                "client_source_group_merge", "medium", "admin",
                "platform.client_resolver", True,
                "Two source groups with the same normalized name are mapped to one client. Review whether they are duplicate source groups.",
            ],
        )
        cursor.execute(
            "SELECT policy FROM operations.condition_policy_versions WHERE version=%s",
            (SOURCE_VERSION,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Required policy {SOURCE_VERSION} is not available")
        policy = row[0]
        if isinstance(policy, str):
            policy = json.loads(policy)
        policy = json.loads(json.dumps(policy))
        policy["version"] = NEW_VERSION
        for category in policy["issue_taxonomy"]:
            for type_item in category.get("types", []):
                if type_item.get("key") == "client_source_mapping":
                    type_item["label"] = "Client source mapping"
                    conditions = type_item.setdefault("conditions", [])
                    if "client_source_group_merge" not in conditions:
                        conditions.append("client_source_group_merge")
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        cursor.execute(
            "SELECT operations.create_condition_policy_version(%s, %s, %s::jsonb)",
            (NEW_VERSION, digest, json.dumps(policy, separators=(",", ":"))),
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0201_client_source_mapping_decisions"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(BRIDGE_SQL, migrations.RunSQL.noop),
        migrations.RunPython(seed_finding_type_and_policy, migrations.RunPython.noop),
    ]
