"""Let a client set its own "offline after" days.

Stage 2 of the single offline definition. The Device status page holds the
tenant value; a client may override it on its Configuration tab. Empty means
use the tenant value, so deploying this changes no findings.
"""

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0293_software_title_main_publisher"),
    ]
    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="client",
            name="offline_after_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
