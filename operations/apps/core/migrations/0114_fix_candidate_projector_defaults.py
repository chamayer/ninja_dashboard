import importlib
from typing import ClassVar

from django.db import migrations

contracts = importlib.import_module(
    "apps.core.migrations.0111_relationship_candidate_event_contracts"
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0113_relationship_evidence_history_security"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(contracts.PROJECTOR_SQL, migrations.RunSQL.noop),
    ]
