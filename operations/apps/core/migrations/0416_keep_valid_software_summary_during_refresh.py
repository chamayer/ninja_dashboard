"""An automatic refresh alone does not invalidate a completed generation."""
from importlib import import_module
from django.db import migrations

OLD_SQL = import_module("apps.core.migrations.0412_activate_software_overview").READ
OLD_CONDITION = "status = 'queued' AND wait_category = 'dependency'\n                    AND "
assert OLD_SQL.count(OLD_CONDITION) == 1
FORWARD_SQL = OLD_SQL.replace(OLD_CONDITION, "", 1)

class Migration(migrations.Migration):
    dependencies = [("operations", "0415_software_executed_input_checkpoints")]
    operations = [migrations.RunSQL(FORWARD_SQL, OLD_SQL)]
