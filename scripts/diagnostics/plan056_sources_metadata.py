"""Read public schema/privilege metadata for the reviewed view replacement."""
import json
import os
import signal
import sys
signal.alarm(15)
sys.path.insert(0,'/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod')
import django
django.setup()
from django.db import connection, transaction
try:
    with transaction.atomic(),connection.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute("SELECT has_table_privilege(relowner,'operations.v_entity_observation_admin_metadata','SELECT'), reloptions FROM pg_class WHERE oid='operations.v_source_instance_record_counts'::regclass")
        print(json.dumps({'owner_metadata_access_and_options':cur.fetchone()}),flush=True)
        cur.execute("SELECT attname,format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='operations.v_source_instance_record_counts'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum")
        print(json.dumps({'existing_columns':cur.fetchall()}),flush=True)
        cur.execute("SELECT name FROM operations.django_migrations WHERE app='operations' AND name LIKE '041%' ORDER BY name")
        print(json.dumps({'migration_state':cur.fetchall()}),flush=True)
finally:
    connection.close()
