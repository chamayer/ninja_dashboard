from django.core.management.base import BaseCommand

from ingest.retention_observations import purge


class Command(BaseCommand):
    help = "Delete closed observation-history intervals older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        deleted = purge(
            tenant_id=options["tenant_id"],
            days=options["days"],
            batch_size=options["batch_size"],
        )
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} history rows"))
