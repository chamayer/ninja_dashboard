"""Hostname leaves the generic attribute authority (ADR-0034 section 10).

Identity names a Computer (``operations.write_computer_names``); the device
cache projector no longer reads the effective hostname. The hostname rows of
``attribute_authority_policies`` are retired (disabled, kept for history).
Hostname claims stay visible evidence: ADR-0010 allows unconfigured
attributes as evidence. Claims carry their policy from projection time and
are re-derived on their normal path; no projection state is invalidated,
since nothing consumes the effective hostname any more.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'attribute_authority.retire_hostname',
    'ADR-0034: identity names Computers; hostname leaves the generic attribute authority.',
    '{"migration": "0329_retire_hostname_authority"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0329', NULL, true);

UPDATE operations.attribute_authority_policies policy
   SET enabled = FALSE,
       reason = 'ADR-0034: identity names Computers.',
       version = policy.version + 1
  FROM operations.attribute_definitions definition
 WHERE definition.id = policy.attribute_definition_id
   AND definition.key = 'hostname'
   AND policy.enabled;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0328_computer_name_writer"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
