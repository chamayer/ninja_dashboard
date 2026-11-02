"""Close the four source failures the old collector raised per Ninja step.

Before failures were tracked per source binding, the collector raised one
failure per collection step (``core.devices``, ``core.device_health``,
``core.custom_fields``, ``patch_cycle``). The findings conversion (0364) gave
them synthetic ``source_binding`` subjects that match no binding, and nothing
has reported under these keys since 2026-09-16; every step now reports under
the NinjaOne binding's own failure. Close them with the reason, keeping their
original details.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE operations.findings f
   SET status = 'resolved', closed_at = now(),
       finding_details = f.finding_details || jsonb_build_object(
           'closure_reason',
           'Superseded: collection steps now report under the NinjaOne source''s own failure; '
           || 'nothing has reported under this step key since 2026-09-16.')
  FROM operations.finding_types ft
 WHERE ft.id = f.finding_type_id AND ft.name = 'source_failure'
   AND f.condition_namespace = 'entity'
   AND f.condition_key IN ('source_failure:core.devices', 'source_failure:core.device_health',
                           'source_failure:core.custom_fields', 'source_failure:patch_cycle')
   AND f.status IN ('open', 'acknowledged', 'investigating')
   AND NOT EXISTS (SELECT 1 FROM operations.source_bindings b WHERE b.id = f.subject_id);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0395_relationship_projector_cardinality"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
