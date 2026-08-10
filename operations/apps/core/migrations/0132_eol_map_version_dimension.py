"""Migration 0132 -- version dimension on the EOL mapping, state only.

SQL migration 082 adds `version_pattern` and `eol_cycle` to
`operations.eol_product_map`. As with 0131, the columns are owned by the ingest
migration runner, so this declares them to Django's state and issues no DDL --
a plain AddField would fail on columns that already exist.

Why the SQL side owns them: `ingest/intel/eol_match.py` reads both columns, and
the two migration runners have no ordering guarantee between them. Ingest
applies its own migrations in-process before its scheduler starts, so the
projector can never see a table without them. The reverse -- letting Django own
the columns -- would leave a window where the projector queries a column Django
has not created yet.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0131_eol_product_map_model'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='eolproductmap',
                    name='eol_cycle',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text=(
                            "Optional explicit release cycle. Blank derives it "
                            "from the installed version, which is right for "
                            "numerically versioned software and impossible for "
                            "cycles like '20h2' or '2008-r2-sp1'."
                        ),
                        max_length=120,
                    ),
                ),
                migrations.AddField(
                    model_name='eolproductmap',
                    name='version_pattern',
                    field=models.CharField(
                        blank=True,
                        default='',
                        help_text=(
                            "Optional ILIKE pattern over the installed version. "
                            "Blank applies to every version. Use it to split one "
                            "title across cycles, e.g. '14.%' for Office 2010."
                        ),
                        max_length=255,
                    ),
                ),
            ],
        ),
    ]
