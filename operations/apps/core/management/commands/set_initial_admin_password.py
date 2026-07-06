"""Set the seeded admin user's password from an env var.

Runs at container startup (called from entrypoint.sh) while the DB
connection is still using operations_migrate (SUPERUSER, bypasses RLS).
That's the only way to touch the admin row post-seed, because the
seeded admin has an unusable password and the runtime operations_app
role can't see the row due to RLS + no tenant GUC in a manage.py
context.

Idempotent: skips silently if the env var isn't set. Skips with a
warning if the admin row is missing.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Set the admin user's password from OPERATIONS_INITIAL_ADMIN_PASSWORD."

    def handle(self, *args, **options) -> None:
        password = os.environ.get("OPERATIONS_INITIAL_ADMIN_PASSWORD", "").strip()
        if not password:
            self.stdout.write(
                "[set_initial_admin_password] OPERATIONS_INITIAL_ADMIN_PASSWORD "
                "not set; skipping."
            )
            return

        User = get_user_model()
        # Explicit tenant_id filter — this command runs as operations_migrate
        # which bypasses RLS, so we can't rely on RLS to scope us to tenant 1.
        user = User.objects.filter(tenant_id=1, username="admin").first()
        if user is None:
            self.stdout.write(
                self.style.WARNING(
                    "[set_initial_admin_password] admin user not found in tenant 1; "
                    "skipping. Migration 0007 should have seeded it."
                )
            )
            return

        user.set_password(password)
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["password", "is_active", "is_staff", "is_superuser"])
        self.stdout.write(
            self.style.SUCCESS(
                "[set_initial_admin_password] admin password updated from env."
            )
        )
