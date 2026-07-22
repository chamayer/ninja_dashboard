"""Replace migration-time software baseline hashes with the live SHA-256 policy."""

import hashlib
import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction


def _hash_material(publisher, version, location, install_date):
    payload = json.dumps(
        {
            "install_date": install_date,
            "location": location,
            "publisher": publisher,
            "version": version,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).digest()


class Command(BaseCommand):
    help = "Normalize open software baseline hashes to the current SHA-256 policy."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=1)
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        batch_size = options["batch_size"]
        updated = 0
        while True:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])
                cursor.execute(
                    """
                    SELECT c.tenant_id, c.client_id, c.device_id, c.canonical_name,
                           c.publisher, c.version, c.install_location, c.install_date,
                           h.id
                      FROM operations.software_installations_current c
                      JOIN operations.software_installation_history h
                        ON h.tenant_id = c.tenant_id
                       AND h.source_binding_id = '00000000-0000-4000-8000-000000000011'::uuid
                       AND h.client_id = c.client_id AND h.device_id = c.device_id
                       AND h.canonical_name = c.canonical_name AND h.effective_to IS NULL
                     WHERE c.tenant_id = %s AND c.material_hash IS NULL
                     ORDER BY c.client_id, c.device_id, c.canonical_name
                     LIMIT %s
                     FOR UPDATE OF c, h SKIP LOCKED
                    """,
                    [tenant_id, batch_size],
                )
                rows = cursor.fetchall()
                if not rows:
                    break
                if options["dry_run"]:
                    updated += len(rows)
                    break
                for (
                    tenant,
                    client,
                    device,
                    name,
                    publisher,
                    version,
                    location,
                    install_date,
                    history_id,
                ) in rows:
                    digest = _hash_material(publisher, version, location, install_date)
                    cursor.execute(
                        """
                        UPDATE operations.software_installations_current
                           SET material_hash = %s, hash_algorithm_version = 1
                         WHERE tenant_id = %s AND client_id = %s AND device_id = %s
                           AND canonical_name = %s AND material_hash IS NULL
                        """,
                        [digest, tenant, client, device, name],
                    )
                    cursor.execute(
                        """
                        UPDATE operations.software_installation_history
                           SET material_hash = %s, hash_algorithm_version = 1
                         WHERE id = %s AND hash_algorithm_version = 0
                        """,
                        [digest, history_id],
                    )
                    updated += 1
        prefix = "Would normalize" if options["dry_run"] else "Normalized"
        self.stdout.write(self.style.SUCCESS(f"{prefix} {updated} software baseline hashes"))
