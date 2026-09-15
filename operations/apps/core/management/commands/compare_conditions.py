"""Print an aggregate-only shadow comparison. Intentionally no apply option."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from apps.core.conditions.policy import load_profile
from apps.core.conditions.reader import read_snapshot
from apps.core.conditions.report import build_report


class Command(BaseCommand):
    help = "Compare proposed condition dependencies without changing any finding or subscriber."
    requires_system_checks: ClassVar[list[str]] = []

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--profile", type=Path, help="Optional reviewed shadow JSON profile")
        parser.add_argument("--max-rows", type=int, default=250_000)
        parser.add_argument("--timeout-ms", type=int, default=30_000)
        parser.add_argument(
            "--catalog-only",
            action="store_true",
            help="Validate/display the packaged profile without database access",
        )

    def handle(self, *args, **options):
        try:
            if options["tenant_id"] <= 0:
                raise ValueError("An explicit positive tenant ID is required")
            profile = load_profile(options["profile"])
            if options["catalog_only"]:
                result = {
                    "mode": "catalog_only",
                    "profile_version": profile.version,
                    "profile_sha256": profile.digest,
                    "definitions": list(profile.definitions.values()),
                    "rules": profile.rules,
                    "consumers": profile.consumers,
                }
            else:
                snapshot = read_snapshot(
                    connection,
                    options["tenant_id"],
                    profile,
                    max_rows=options["max_rows"],
                    timeout_ms=options["timeout_ms"],
                )
                result = build_report(snapshot, profile)
        except DatabaseError:
            # Database errors may contain SQL values or connection details.
            raise CommandError(
                "Read-only comparison failed; no report or changes produced. "
                "Check database access, schema compatibility, and query limits."
            ) from None
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise CommandError(
                f"Invalid shadow input ({type(exc).__name__}); no changes made."
            ) from None
        self.stdout.write(json.dumps(result, sort_keys=True, indent=2))
