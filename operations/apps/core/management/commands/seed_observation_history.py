"""Create one explicit baseline history interval for current observation state."""

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Seed open history baselines from current observation tables."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        params = {"tenant_id": tenant_id}
        generic_count_sql = """
            SELECT count(*)
              FROM operations.entity_observation_current c
             WHERE c.tenant_id = %(tenant_id)s AND c.active
               AND NOT EXISTS (
                   SELECT 1 FROM operations.entity_observation_history h
                    WHERE h.tenant_id = c.tenant_id
                      AND h.source_binding_id = c.source_binding_id
                      AND h.entity_type = c.entity_type
                      AND h.parent_source_key = c.parent_source_key
                      AND h.entity_key = c.entity_key AND h.effective_to IS NULL
               )
        """
        software_count_sql = """
            SELECT count(*)
              FROM operations.software_installations_current c
             WHERE c.tenant_id = %(tenant_id)s AND c.stale_since IS NULL
               AND c.deleted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM operations.software_installation_history h
                    WHERE h.tenant_id = c.tenant_id
                      AND h.source_binding_id = '00000000-0000-4000-8000-000000000011'::uuid
                      AND h.client_id = c.client_id AND h.device_id = c.device_id
                      AND h.canonical_name = c.canonical_name AND h.effective_to IS NULL
               )
        """
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])
            cursor.execute(generic_count_sql, params)
            generic_count = cursor.fetchone()[0]
            cursor.execute(software_count_sql, params)
            software_count = cursor.fetchone()[0]
            if options["dry_run"]:
                self.stdout.write(
                    f"Would seed {generic_count} generic and {software_count} software history baselines"
                )
                return
            cursor.execute(
                """
                INSERT INTO operations.entity_observation_history
                  (id, tenant_id, source_binding_id, collector_instance_id,
                   client_id, device_id, entity_type, platform, parent_source_key,
                   entity_key, effective_from, effective_to, last_seen_at,
                   received_at, material_data, material_hash,
                   hash_algorithm_version, active)
                SELECT gen_random_uuid(), c.tenant_id, c.source_binding_id,
                       c.collector_instance_id, c.client_id, c.device_id,
                       c.entity_type, c.platform, c.parent_source_key, c.entity_key,
                       c.observed_at, NULL, c.last_seen_at, c.last_received_at,
                       c.canonical_data - ARRAY['last_seen_at', 'last_contact',
                         'is_online', 'offline', 'hostStateChangeDate', 'lastActive',
                         'last_boot_time_at', 'power_state'],
                       c.material_hash, c.hash_algorithm_version, TRUE
                  FROM operations.entity_observation_current c
                 WHERE c.tenant_id = %(tenant_id)s AND c.active
                   AND NOT EXISTS (
                       SELECT 1 FROM operations.entity_observation_history h
                        WHERE h.tenant_id = c.tenant_id
                          AND h.source_binding_id = c.source_binding_id
                          AND h.entity_type = c.entity_type
                          AND h.parent_source_key = c.parent_source_key
                          AND h.entity_key = c.entity_key AND h.effective_to IS NULL
                   )
                """,
                params,
            )
            generic_inserted = cursor.rowcount
            cursor.execute(
                """
                INSERT INTO operations.software_installation_history
                  (id, tenant_id, source_binding_id, client_id, device_id,
                   canonical_name, publisher, version, install_location,
                   install_date, material_hash, hash_algorithm_version,
                   effective_from, effective_to, last_seen_at, received_at, active)
                SELECT gen_random_uuid(), c.tenant_id,
                       '00000000-0000-4000-8000-000000000011'::uuid,
                       c.client_id, c.device_id, c.canonical_name, c.publisher,
                       c.version, c.install_location, c.install_date,
                       decode(md5(jsonb_build_object('publisher', c.publisher,
                         'version', c.version, 'location', c.install_location,
                         'install_date', c.install_date)::text), 'hex'),
                       0, c.last_observed_at, NULL, c.last_observed_at,
                       c.refreshed_at, TRUE
                  FROM operations.software_installations_current c
                 WHERE c.tenant_id = %(tenant_id)s AND c.stale_since IS NULL
                   AND c.deleted_at IS NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM operations.software_installation_history h
                        WHERE h.tenant_id = c.tenant_id
                          AND h.source_binding_id = '00000000-0000-4000-8000-000000000011'::uuid
                          AND h.client_id = c.client_id AND h.device_id = c.device_id
                          AND h.canonical_name = c.canonical_name AND h.effective_to IS NULL
                   )
                """,
                params,
            )
            software_inserted = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {generic_inserted} generic and {software_inserted} software history baselines"
            )
        )
