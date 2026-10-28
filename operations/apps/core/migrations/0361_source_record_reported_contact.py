"""Expose guarded per-record contact without granting access to payloads."""

from __future__ import annotations

from importlib import import_module
from typing import ClassVar

from django.db import migrations

_previous = import_module("apps.core.migrations.0360_source_record_reported_state")
_old = "END AS reported_online"
_new = (
    _old
    + r""",
       CASE WHEN NOT restricted.is_restricted
                 AND btrim(observation.canonical_data->>'last_seen_at')
                     ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$'
                 AND pg_input_is_valid(
                     observation.canonical_data->>'last_seen_at', 'timestamp with time zone')
            THEN CASE WHEN extract(year FROM
                          (observation.canonical_data->>'last_seen_at')::timestamptz) > 1
                      THEN (observation.canonical_data->>'last_seen_at')::timestamptz
                 END
       END AS reported_last_contact_at"""
)
assert _previous.FORWARD_SQL.count(_old) == 1
FORWARD_SQL = _previous.FORWARD_SQL.replace(_old, _new)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0360_source_record_reported_state"),
    ]
    # Reverting the application does not require dropping the additive column.
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
