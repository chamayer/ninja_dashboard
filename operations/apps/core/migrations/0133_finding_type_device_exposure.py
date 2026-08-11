"""Migration 0133 -- creates_device_exposure on FindingType, state only.

SQL migration 084 adds the column and sets it false for whitelist_suggestion.
It has to, because the exposure view it rebuilds reads the column, and the two
migration runners have no ordering guarantee between them -- ingest applies its
own SQL in-process before its scheduler starts, so the view can never see a
finding_types without it. Letting Django own the column would leave a window
where the view references something not yet created.

Same state-only pattern as 0131 and 0132.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0132_eol_map_version_dimension'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='findingtype',
                    name='creates_device_exposure',
                    field=models.BooleanField(
                        default=True,
                        help_text=(
                            'Uncheck when a finding of this type is about the '
                            'software rather than any device running it, so it '
                            'must not fan out across installations. '
                            'whitelist_suggestion is the case this exists for: '
                            'it asks whether to allow a title, which needs a '
                            'device count, not a device list.'
                        ),
                    ),
                ),
            ],
        ),
    ]
