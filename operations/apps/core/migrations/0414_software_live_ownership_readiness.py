"""Do not wait for ownership reconciliation of deleted Computers."""
from importlib import import_module
from django.db import migrations

OLD_SQL = import_module("apps.core.migrations.0412_activate_software_overview").INPUTS
OLD_GUARD = """SELECT 1 FROM operations.computer_client_ownership
             WHERE tenant_id = p_tenant AND state = 'dirty'"""
NEW_GUARD = """SELECT 1 FROM operations.computer_client_ownership owner
              JOIN operations.devices device
                ON device.tenant_id = owner.tenant_id AND device.id = owner.device_id
               AND device.deleted_at IS NULL
             WHERE owner.tenant_id = p_tenant AND owner.state = 'dirty'"""
assert OLD_SQL.count(OLD_GUARD) == 1
FORWARD_SQL = OLD_SQL.replace(OLD_GUARD, NEW_GUARD, 1)

class Migration(migrations.Migration):
    dependencies = [("operations", "0412_activate_software_overview")]
    operations = [migrations.RunSQL(FORWARD_SQL, OLD_SQL)]
