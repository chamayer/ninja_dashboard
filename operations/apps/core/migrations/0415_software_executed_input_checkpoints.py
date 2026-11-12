"""An unexecuted workflow attempt is not an input publication."""
from importlib import import_module
from django.db import migrations

OLD_SQL = import_module("apps.core.migrations.0414_software_live_ownership_readiness").FORWARD_SQL
OLD_FILTER = "WHERE r.tenant_id = p_tenant AND r.status <> 'queued' "
NEW_FILTER = OLD_FILTER + "AND (r.started_at IS NOT NULL OR r.status = 'completed') "
assert OLD_SQL.count(OLD_FILTER) == 1
FORWARD_SQL = OLD_SQL.replace(OLD_FILTER, NEW_FILTER, 1)

class Migration(migrations.Migration):
    dependencies = [("operations", "0414_software_live_ownership_readiness")]
    operations = [migrations.RunSQL(FORWARD_SQL, OLD_SQL)]
