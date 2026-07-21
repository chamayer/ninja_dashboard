from django.db import migrations


def configure_observation_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in ("entity_observation_current", "entity_observation_history", "observation_snapshot_runs"):
        schema_editor.execute(f"ALTER TABLE operations.{table} ENABLE ROW LEVEL SECURITY")
        schema_editor.execute(f"ALTER TABLE operations.{table} FORCE ROW LEVEL SECURITY")
        schema_editor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON operations.{table}")
        schema_editor.execute(f"""
            CREATE POLICY tenant_isolation ON operations.{table}
            USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
            WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
        """)
        schema_editor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON operations.{table} TO operations_app")
        schema_editor.execute(f"GRANT SELECT ON operations.{table} TO operations_readonly")
        schema_editor.execute(f"GRANT SELECT, INSERT, UPDATE ON operations.{table} TO ninja_ingest")


class Migration(migrations.Migration):
    dependencies = [("operations", "0065_alter_coveragerequirement_options_and_more")]
    operations = [migrations.RunPython(configure_observation_rls, migrations.RunPython.noop)]
