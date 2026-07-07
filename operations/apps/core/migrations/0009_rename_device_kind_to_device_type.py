from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0008_alter_device_device_kind"),
    ]

    operations = [
        migrations.RenameField(
            model_name="device",
            old_name="device_kind",
            new_name="device_type",
        ),
    ]
