from django.db import migrations


def move_queue_target(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            """
            UPDATE operations.queue_registry
               SET table_name = 'operations.entity_observation_current'
             WHERE queue_key = 'identity.resolution'
               AND table_name = 'operations.entity_observations'
            """
        )


class Migration(migrations.Migration):
    dependencies = [("operations", "0068_refresh_software_from_current")]
    operations = [migrations.RunPython(move_queue_target, migrations.RunPython.noop)]
