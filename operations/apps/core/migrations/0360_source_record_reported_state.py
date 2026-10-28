"""Expose each source record's reported online state in safe metadata."""

from __future__ import annotations

from importlib import import_module
from typing import ClassVar

from django.db import migrations

_previous = import_module("apps.core.migrations.0348_observation_domain")
_old = "THEN nullif(btrim(observation.canonical_data->>'domain'), '') END AS canonical_domain"
_new = _old + """,
       CASE WHEN NOT restricted.is_restricted THEN
           CASE lower(observation.canonical_data->>'is_online')
               WHEN 'true' THEN TRUE WHEN 't' THEN TRUE WHEN '1' THEN TRUE WHEN 'yes' THEN TRUE WHEN 'online' THEN TRUE
               WHEN 'false' THEN FALSE WHEN 'f' THEN FALSE WHEN '0' THEN FALSE WHEN 'no' THEN FALSE WHEN 'offline' THEN FALSE
           END
       END AS reported_online"""
assert _old in _previous.FORWARD_SQL
FORWARD_SQL = _previous.FORWARD_SQL.replace(_old, _new).replace(
    ", metabase_ro", ""
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [("operations", "0359_drop_metabase_ro_role")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
