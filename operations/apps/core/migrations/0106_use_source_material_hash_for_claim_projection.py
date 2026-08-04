"""Use the generic source material hash for cheap claim no-op detection."""

from importlib import import_module

from django.db import migrations


PROJECTOR_SQL = import_module(
    f"{__package__}.0103_attribute_claim_projection"
).PROJECTOR_SQL


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0105_use_builtin_attribute_claim_sha256"),
    ]

    operations = [
        migrations.RunSQL(PROJECTOR_SQL, migrations.RunSQL.noop),
    ]
