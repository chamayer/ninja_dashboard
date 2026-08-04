"""Replace the claim projector with PostgreSQL's built-in SHA-256 function."""

from importlib import import_module

from django.db import migrations


PROJECTOR_SQL = import_module(
    f"{__package__}.0103_attribute_claim_projection"
).PROJECTOR_SQL


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0104_qualify_attribute_claim_digest"),
    ]

    operations = [
        migrations.RunSQL(PROJECTOR_SQL, migrations.RunSQL.noop),
    ]
