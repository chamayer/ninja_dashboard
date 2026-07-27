from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Seed observation current state from the latest legacy row per identity."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        params = {"tenant_id": tenant_id}
        identity = "''::text"
        latest = f"""
            SELECT DISTINCT ON (o.tenant_id, o.source_binding_id, o.entity_type,
                                {identity}, o.entity_key)
                   o.*, {identity} AS parent_source_key,
                   CASE WHEN o.entity_type = 'software' THEN 'Ninja.software'
                        ELSE COALESCE(NULLIF(si.config->>'source_key', ''),
                                      NULLIF(si.config->>'source_name', ''),
                                      s.name, o.platform) END AS snapshot_scope
              FROM operations.entity_observations o
              LEFT JOIN operations.source_bindings sb ON sb.id = o.source_binding_id
             LEFT JOIN operations.source_instances si ON si.id = sb.source_instance_id
             LEFT JOIN operations.sources s ON s.id = si.source_id
             WHERE o.tenant_id = %(tenant_id)s
               AND o.entity_type <> 'software'
             ORDER BY o.tenant_id, o.source_binding_id, o.entity_type,
                      parent_source_key, o.entity_key, o.observed_at DESC, o.observation_id DESC
        """
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])
            cursor.execute(f"SELECT count(*) FROM ({latest}) latest", params)
            candidates = cursor.fetchone()[0]
        if options["dry_run"]:
            self.stdout.write(f"Would seed {candidates} current identities")
            return

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])
            cursor.execute(
                f"""
                INSERT INTO operations.entity_observation_current
                  (observation_id, tenant_id, source_binding_id, collector_instance_id,
                   client_id, device_id, entity_type, parent_source_key, entity_key,
                   platform, subplatform, observed_at, last_seen_at, last_received_at,
                   active, withdrawn_at, snapshot_scope, last_snapshot_run_id,
                   raw_data, canonical_data, raw_hash, material_hash,
                   hash_algorithm_version, batch_id, collector_version, schema_version)
                SELECT observation_id, tenant_id, source_binding_id, collector_instance_id,
                       client_id, device_id, entity_type, parent_source_key, entity_key,
                       platform, subplatform, observed_at, observed_at, clock_timestamp(),
                       TRUE, NULL, snapshot_scope, NULL,
                       raw_data, canonical_data, NULL,
                       decode(md5((canonical_data - ARRAY['last_seen_at','last_contact',
                         'offline','hostStateChangeDate','lastActive','last_boot_time_at'])::text), 'hex'),
                       0, batch_id, collector_version, schema_version
                  FROM ({latest}) latest
                ON CONFLICT (tenant_id, source_binding_id, entity_type,
                             parent_source_key, entity_key)
                DO UPDATE SET
                    client_id = EXCLUDED.client_id, device_id = EXCLUDED.device_id,
                    platform = EXCLUDED.platform, subplatform = EXCLUDED.subplatform,
                    observed_at = EXCLUDED.observed_at, last_seen_at = EXCLUDED.last_seen_at,
                    last_received_at = EXCLUDED.last_received_at, active = TRUE,
                    withdrawn_at = NULL, snapshot_scope = EXCLUDED.snapshot_scope,
                    raw_data = EXCLUDED.raw_data, canonical_data = EXCLUDED.canonical_data,
                    material_hash = EXCLUDED.material_hash,
                    hash_algorithm_version = EXCLUDED.hash_algorithm_version,
                    batch_id = EXCLUDED.batch_id,
                    collector_version = EXCLUDED.collector_version,
                    schema_version = EXCLUDED.schema_version
                WHERE operations.entity_observation_current.observed_at <= EXCLUDED.observed_at
                """,
                params,
            )
            affected = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(f"Seeded or refreshed {affected} of {candidates} current identities")
        )
