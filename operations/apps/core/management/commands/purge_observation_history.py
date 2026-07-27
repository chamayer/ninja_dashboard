"""Purge closed observation history beyond the approved retention window."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Purge closed generic and software history older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM operations.purge_closed_observation_history(%s)",
                [cutoff],
            )
            generic, software = cursor.fetchone()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {generic} generic and {software} software closed history rows before {cutoff.isoformat()}"
            )
        )
