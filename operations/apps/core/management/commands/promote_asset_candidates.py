"""Promote CMDB candidates to `asset` entities, scoped by source layout.

`asset` is reserved for things the MSP tracks that are not devices (ADR-0013).
The Hudu CMDB candidates are not one population: measured 2026-08-07, the 4,843
unlinked records span 20 layouts holding real hardware, locations, software,
client attributes and one relationship type. Promoting them wholesale would
make `asset` a catch-all for four other classes.

So promotion is scoped by layout, and the layouts are an **argument**, not a
constant in this file -- there is no defensible hardcoded list, and per
ADR-0012 s6 a domain mapping does not belong in code. When the layout ->
entity_type mapping table lands, this command reads it instead.

Dry run by default: it reports the per-layout counts it would create and
writes nothing.

Usage::

    python manage.py promote_asset_candidates --layouts "Servers,Printing"
    python manage.py promote_asset_candidates --layouts "..." --apply

Sets the tenant GUC before querying: `operations.users` and the entity tables
carry forced RLS, and a management command runs outside the request cycle where
middleware would normally set it. Without it every query returns zero rows and
the command reports "nothing to promote" rather than failing.

Idempotent: a candidate already `attached` is skipped, and `promote_candidate`
refuses it anyway. Re-running after adding a layout promotes only the new one.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.entity_candidate_decisions import promote_candidate
from apps.core.models import EntityCandidate

REASON = "bulk promotion of unlinked CMDB hardware records to the asset class"


class Command(BaseCommand):
    help = "Promote asset-class candidates for the named source layouts (dry run by default)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--layouts",
            required=True,
            help="Comma-separated source layout names to promote, e.g. 'Servers,Printing'.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command only reports.",
        )
        parser.add_argument("--tenant", type=int, default=1)

    def handle(self, *args, **options) -> None:
        tenant_id = options["tenant"]
        layouts = [name.strip() for name in options["layouts"].split(",") if name.strip()]
        if not layouts:
            raise CommandError("--layouts must name at least one layout")

        self._set_tenant(tenant_id)
        actor = self._actor()

        planned = self._plan(tenant_id, layouts)
        total = sum(len(ids) for ids in planned.values())

        self.stdout.write(f"layouts requested : {', '.join(layouts)}")
        for layout, ids in sorted(planned.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f"  {layout:<24} {len(ids):>6}")
        self.stdout.write(f"  {'TOTAL':<24} {total:>6}")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("dry run -- nothing written. Re-run with --apply.")
            )
            return

        created, skipped = self._write(planned, actor)
        self.stdout.write(
            self.style.SUCCESS(f"applied: promoted={created} skipped={skipped}")
        )

    def _set_tenant(self, tenant_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('operations.tenant_id', %s, false)", [str(tenant_id)]
            )

    def _actor(self):
        users = get_user_model().objects
        actor = (
            users.filter(is_superuser=True).order_by("id").first()
            or users.order_by("id").first()
        )
        if actor is None:
            raise CommandError("no user exists to attribute the promotions to")
        return actor

    def _plan(self, tenant_id: int, layouts: list[str]) -> dict[str, list[str]]:
        """Candidate ids per layout, joined through the observation's layout.

        The candidate carries the stable source identity; the layout lives on
        the observation's `canonical_data`. They join on the same external id
        within the same source instance.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT observation.canonical_data->>'hudu_layout' AS layout,
                       candidate.id
                  FROM operations.entity_candidates candidate
                  JOIN operations.entity_observation_current observation
                    ON observation.tenant_id = candidate.tenant_id
                   AND observation.source_instance_id = candidate.source_instance_id
                   AND observation.external_namespace = candidate.external_namespace
                   AND observation.external_id = candidate.external_id
                 WHERE candidate.tenant_id = %s
                   AND candidate.proposed_entity_class_id = 'asset'
                   AND candidate.status <> 'attached'
                   AND candidate.status <> 'rejected'
                   AND observation.active
                   AND observation.canonical_data->>'hudu_layout' = ANY(%s)
                """,
                [tenant_id, layouts],
            )
            rows = cursor.fetchall()

        planned: dict[str, list[str]] = {}
        for layout, candidate_id in rows:
            planned.setdefault(layout or "(none)", []).append(candidate_id)
        return planned

    def _write(self, planned: dict[str, list[str]], actor) -> tuple[int, int]:
        created = skipped = 0
        for layout, ids in planned.items():
            for candidate_id in ids:
                # One transaction per candidate: a single bad row must not
                # roll back thousands of good promotions.
                try:
                    with transaction.atomic():
                        candidate = EntityCandidate.objects.get(id=candidate_id)
                        promote_candidate(
                            actor=actor,
                            candidate=candidate,
                            reason=f"{REASON} ({layout})",
                        )
                    created += 1
                except Exception as exc:  # reported per row, never silent
                    skipped += 1
                    self.stderr.write(f"  skipped {candidate_id} ({layout}): {exc}")
        return created, skipped
