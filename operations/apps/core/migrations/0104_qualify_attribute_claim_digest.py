"""Qualify pgcrypto calls inside the restricted claim-projector search path."""

from importlib import import_module

from django.db import migrations


PROJECTOR_SQL = import_module(
    f"{__package__}.0103_attribute_claim_projection"
).PROJECTOR_SQL


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0103_attribute_claim_projection"),
    ]

    operations = [
        migrations.RunSQL(PROJECTOR_SQL, migrations.RunSQL.noop),
    ]
