"""Exclude endpoint-specific health evidence from device presence.

Ninja device detail and device health are deliberately distinct source-record
namespaces linked to the same canonical device.  Device detail already carries
Ninja's device-presence signal; projecting device health as a second presence
row creates duplicate per-platform keys and can also obscure higher-fidelity
contact and VM power evidence.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_PRESENCE_PREDICATE = "WHERE o.active AND o.device_id IS NOT NULL AND o.entity_type <> 'software'"
_FILTERED_PRESENCE_PREDICATE = (
    f"{_PRESENCE_PREDICATE}\n  AND o.external_namespace <> 'device-health'"
)

# Migration 0077 is the latest definition of this materialized-view chain;
# later migrations do not redefine any of these four read models.  Reuse that
# immutable migration SQL so dependent view definitions cannot drift during
# this targeted replacement.
_BASE_SQL = importlib.import_module(
    "apps.core.migrations.0077_latest_reported_online_state"
).FORWARD_SQL
if _BASE_SQL.count(_PRESENCE_PREDICATE) != 1:
    raise RuntimeError("unexpected device-presence definition in migration 0077")

FORWARD_SQL = _BASE_SQL.replace(
    _PRESENCE_PREDICATE,
    _FILTERED_PRESENCE_PREDICATE,
)


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0097_ninja_snapshot_expand")]
    # Reintroducing the duplicate projection while health rows exist is not a
    # safe rollback. Older application releases remain compatible with the
    # filtered read model, so schema rollback intentionally keeps the repair.
    operations: ClassVar = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
