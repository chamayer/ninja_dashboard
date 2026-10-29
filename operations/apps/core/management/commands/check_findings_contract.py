"""Refuse to serve when the database findings contract differs from this build.

Operations applies its own migrations before this runs, so a mismatch means
this image is older or newer than the database (PLAN-003 R2). Exit non-zero so
the entrypoint stops before Gunicorn accepts traffic.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from shared.findings_contract import FINDING_CONTRACT, database_findings_contract


class Command(BaseCommand):
    help = "Fail unless the database accepts this build's findings writer contract."

    def handle(self, *args, **options) -> None:
        with connection.cursor() as cursor:
            current = database_findings_contract(cursor)
        if current != FINDING_CONTRACT:
            raise CommandError(
                f"findings contract {FINDING_CONTRACT} required, database has {current}"
            )
        self.stdout.write(f"findings contract {current} matches")
