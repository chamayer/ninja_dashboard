"""Make the normalized MAC address an ordinary internal device field."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("operations", "0150_hudu_computer_evidence_read_model")]

    operations = [
        migrations.RunSQL(
            """
            UPDATE operations.attribute_definitions
               SET sensitivity = 'internal'
             WHERE key = 'mac_address' AND sensitivity = 'sensitive'
            """,
            migrations.RunSQL.noop,
        )
    ]
