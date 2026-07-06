from __future__ import annotations

from django.db import migrations


TENANT_SCOPED_TABLES = (
    "users",
    "user_groups",
    "user_permissions",
    "clients",
    "client_links",
    "client_policies",
    "devices",
    "device_links",
    "client_users",
    "client_user_links",
    "source_instances",
    "collector_instances",
    "source_bindings",
    "entity_observations",
    "dead_letter_observations",
    "software_decisions",
    "software_installations_current",
    "merge_candidates",
    "findings",
    "suppression_rules",
    "notification_routes",
    "audit_log",
    "secrets",
    "run_log",
)

LAYERED_TABLES = ("software_catalog",)

ROLES = (
    "operations_app",
    "operations_migrate",
    "operations_readonly",
    "operations_health",
    "metabase_ro",
    "ninja_ingest",
)


def configure_rls_roles_policies_grants(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    for role in ROLES:
        schema_editor.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = '{role}'
                ) THEN
                    CREATE ROLE {role};
                END IF;
            END
            $$;
            """
        )

    schema_editor.execute("ALTER ROLE operations_migrate BYPASSRLS")
    schema_editor.execute("ALTER ROLE operations_app NOBYPASSRLS")
    schema_editor.execute("ALTER ROLE operations_readonly NOBYPASSRLS")
    schema_editor.execute("ALTER ROLE metabase_ro NOBYPASSRLS")
    schema_editor.execute("ALTER ROLE ninja_ingest NOBYPASSRLS")

    for table in TENANT_SCOPED_TABLES:
        schema_editor.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('operations.{table}') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE operations.{table}
                        ENABLE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE operations.{table}
                        FORCE ROW LEVEL SECURITY';
                    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation
                        ON operations.{table}';
                    EXECUTE 'CREATE POLICY tenant_isolation
                        ON operations.{table}
                        USING (
                            tenant_id = current_setting(
                                ''operations.tenant_id'', TRUE
                            )::bigint
                        )';
                    EXECUTE 'ALTER TABLE operations.{table}
                        OWNER TO operations_migrate';
                END IF;
            END
            $$;
            """
        )

    for table in LAYERED_TABLES:
        schema_editor.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('operations.{table}') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE operations.{table}
                        ENABLE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE operations.{table}
                        FORCE ROW LEVEL SECURITY';
                    EXECUTE 'DROP POLICY IF EXISTS tenant_or_global
                        ON operations.{table}';
                    EXECUTE 'CREATE POLICY tenant_or_global
                        ON operations.{table}
                        USING (
                            tenant_id IS NULL
                            OR tenant_id = current_setting(
                                ''operations.tenant_id'', TRUE
                            )::bigint
                        )';
                    EXECUTE 'ALTER TABLE operations.{table}
                        OWNER TO operations_migrate';
                END IF;
            END
            $$;
            """
        )

    schema_editor.execute("GRANT USAGE ON SCHEMA operations TO operations_app")
    schema_editor.execute("GRANT USAGE ON SCHEMA operations TO operations_readonly")
    schema_editor.execute("GRANT USAGE ON SCHEMA operations TO metabase_ro")
    schema_editor.execute("GRANT USAGE ON SCHEMA operations TO ninja_ingest")

    schema_editor.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON ALL TABLES IN SCHEMA operations
        TO operations_app
        """
    )
    schema_editor.execute(
        """
        GRANT USAGE, SELECT, UPDATE
        ON ALL SEQUENCES IN SCHEMA operations
        TO operations_app
        """
    )
    schema_editor.execute(
        """
        GRANT SELECT
        ON ALL TABLES IN SCHEMA operations
        TO operations_readonly, metabase_ro
        """
    )
    schema_editor.execute(
        """
        GRANT SELECT
        ON ALL SEQUENCES IN SCHEMA operations
        TO operations_readonly, metabase_ro
        """
    )
    schema_editor.execute(
        """
        GRANT SELECT, INSERT
        ON operations.entity_observations,
           operations.dead_letter_observations,
           operations.run_log
        TO ninja_ingest
        """
    )
    schema_editor.execute(
        """
        GRANT EXECUTE ON FUNCTION
            operations.refresh_software_installations_current(bigint)
        TO ninja_ingest, operations_app
        """
    )

    schema_editor.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA operations
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO operations_app
        """
    )
    schema_editor.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA operations
        GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO operations_app
        """
    )
    schema_editor.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA operations
        GRANT SELECT ON TABLES TO operations_readonly, metabase_ro
        """
    )


def reverse_rls_roles_policies_grants(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        REVOKE SELECT, INSERT
        ON operations.entity_observations,
           operations.dead_letter_observations,
           operations.run_log
        FROM ninja_ingest
        """
    )
    schema_editor.execute(
        """
        REVOKE EXECUTE ON FUNCTION
            operations.refresh_software_installations_current(bigint)
        FROM ninja_ingest, operations_app
        """
    )

    for table in (*TENANT_SCOPED_TABLES, *LAYERED_TABLES):
        schema_editor.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('operations.{table}') IS NOT NULL THEN
                    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation
                        ON operations.{table}';
                    EXECUTE 'DROP POLICY IF EXISTS tenant_or_global
                        ON operations.{table}';
                    EXECUTE 'ALTER TABLE operations.{table}
                        NO FORCE ROW LEVEL SECURITY';
                    EXECUTE 'ALTER TABLE operations.{table}
                        DISABLE ROW LEVEL SECURITY';
                END IF;
            END
            $$;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0005_notificationroute_auditlog_finding_mergecandidate_and_more"),
    ]

    operations = [
        migrations.RunPython(
            configure_rls_roles_policies_grants,
            reverse_rls_roles_policies_grants,
        ),
    ]
