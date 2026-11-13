"""Automatic refresh delivery is not a new Software input revision."""
from importlib import import_module

from django.db import migrations

OLD_SQL = import_module(
    "apps.core.migrations.0415_software_executed_input_checkpoints"
).FORWARD_SQL
OLD_FILTER = "AND (q.trigger_kind <> 'dependency' OR q.actor_id IS NOT NULL)"
assert OLD_SQL.count(OLD_FILTER) == 1
# Explicit operator requests still invalidate an in-flight generation. Material
# changes remain fenced by completed owner checkpoints and pending work guards.
FORWARD_SQL = OLD_SQL.replace(OLD_FILTER, "AND q.actor_id IS NOT NULL", 1)


class Migration(migrations.Migration):
    dependencies = [("operations", "0413_group_source_stream_counts")]
    operations = [migrations.RunSQL(FORWARD_SQL, OLD_SQL)]
