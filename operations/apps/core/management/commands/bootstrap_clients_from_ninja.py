"""Upsert operations.clients from ninja_core.organizations.

Idempotent. Keyed on ClientLink(source=Ninja, external_id=<org_id>) so
renaming an org in Ninja updates the existing Client's display_name
without churning the slug (URL stability).

Runs at container startup from entrypoint.sh as operations_migrate
(SUPERUSER, bypasses RLS). Safe to also run manually:

    docker exec ninja-operations python manage.py bootstrap_clients_from_ninja
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils.text import slugify

from apps.core.models import Client, ClientLink, Source

TENANT_ID = 1
NINJA_SOURCE_NAME = "Ninja"


class Command(BaseCommand):
    help = "Upsert Operations clients from ninja_core.organizations."

    def handle(self, *args, **options) -> None:
        if connection.vendor != "postgresql":
            self.stdout.write("[bootstrap_clients_from_ninja] non-postgres backend; skipping.")
            return

        try:
            source = Source.objects.get(name=NINJA_SOURCE_NAME)
        except Source.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    "[bootstrap_clients_from_ninja] Ninja source not seeded; "
                    "run migration 0007. Skipping."
                )
            )
            return

        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name FROM ninja_core.organizations ORDER BY id")
            rows = cursor.fetchall()

        if not rows:
            self.stdout.write("[bootstrap_clients_from_ninja] ninja_core.organizations empty.")
            return

        created = updated = unchanged = 0
        with transaction.atomic():
            for org_id, name in rows:
                external_id = str(org_id)
                link = (
                    ClientLink.objects.select_related("client")
                    .filter(tenant_id=TENANT_ID, source=source, external_id=external_id)
                    .first()
                )
                if link is not None:
                    client = link.client
                    if client.display_name != name or link.external_name != name:
                        client.display_name = name
                        client.save(update_fields=["display_name"])
                        link.external_name = name
                        link.save(update_fields=["external_name"])
                        updated += 1
                    else:
                        unchanged += 1
                    continue

                slug = self._unique_slug(slugify(name) or f"client-{org_id}")
                client = Client.objects.create(
                    tenant_id=TENANT_ID,
                    slug=slug,
                    display_name=name,
                )
                ClientLink.objects.create(
                    tenant_id=TENANT_ID,
                    client=client,
                    source=source,
                    external_id=external_id,
                    external_name=name,
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[bootstrap_clients_from_ninja] created={created} "
                f"updated={updated} unchanged={unchanged} total={len(rows)}"
            )
        )

    @staticmethod
    def _unique_slug(base: str) -> str:
        slug = base
        n = 2
        while Client.objects.filter(tenant_id=TENANT_ID, slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug
