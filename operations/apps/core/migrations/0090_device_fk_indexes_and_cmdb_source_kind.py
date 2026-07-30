"""Index the device foreign keys, and register the CMDB source kind.

Two unrelated-looking changes that came from the same incident.

**FK indexes.** ``software_installations_current`` (1.15 GB) and
``software_installation_history`` (208 MB) both carry a ``device_id`` foreign
key to ``operations.devices`` with ``NO ACTION``, and neither had an index on
it. Every delete of a device therefore sequentially scanned both tables once
*per row*: removing 4,990 devices meant roughly 6.8 TB of scanning and never
completed. With these indexes the same delete ran in 1.9 s. This affects any
device removal — merges, retirement, tenant offboarding — not just cleanup.

**CMDB source kind.** Hudu is registered as an Operations source whose
observations describe assets but establish no per-device identity. The kind
is ``cmdb`` rather than a vendor name so a second CMDB inherits the same
behaviour with no code change: excluded from ``IDENTITY_ENTITY_TYPES`` (never
resolved, promoted, or written to ``device_links``) and placed on the slower
documentation collection cycle. Precedent: ``agent.remote_access`` already
serves both ScreenConnect and LogMeIn.

The source/instance/binding rows themselves are environment configuration and
stay out of migrations — this only ensures the kind is correct where the row
already exists, so a hand-registered instance and a fresh install agree.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE INDEX IF NOT EXISTS idx_software_installations_current_device
    ON operations.software_installations_current (device_id);

CREATE INDEX IF NOT EXISTS idx_software_installation_history_device
    ON operations.software_installation_history (device_id);

UPDATE operations.sources SET kind = 'cmdb'
 WHERE name = 'Hudu' AND kind = 'documentation';
"""

REVERSE_SQL = """
UPDATE operations.sources SET kind = 'documentation'
 WHERE name = 'Hudu' AND kind = 'cmdb';

DROP INDEX IF EXISTS operations.idx_software_installation_history_device;
DROP INDEX IF EXISTS operations.idx_software_installations_current_device;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0089_publisher_category_help_text"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
