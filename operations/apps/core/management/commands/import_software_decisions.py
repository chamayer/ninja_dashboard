"""Import operator software decisions from a legacy `decisions_*.csv`.

The legacy analyser accumulated its decisions in `decisions_global.csv` and
merged on every save so none were ever lost. That corpus is the most expensive
artefact in the software domain to recreate — human judgement about what is
allowed in this fleet — and `operations.software_decisions` held 3 rows
against its 418.

This is a command rather than a data migration on purpose. Decisions are
operator-maintainable data: the corpus can change, an operator may need to
re-run the import after editing it, and burying 418 rows in a migration would
put domain data in code where nobody can see or correct it. See ADR-0015 and
`feedback_mappings_in_data`.

Usage::

    python manage.py import_software_decisions --file /path/decisions_global.csv
    python manage.py import_software_decisions --file ... --apply

Dry run by default: it reports exactly what would change and writes nothing.

Idempotent and non-destructive. Global-scope uniqueness is
`(tenant, canonical_name)` and `(tenant, publisher)`, so a re-run updates
rather than duplicates. A row an operator has since changed in the UI is never
overwritten — the import only touches rows it created itself, identified by
`reason`.
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import SoftwareDecision

IMPORT_REASON = "imported from legacy software decisions CSV"

# The corpus carries both `Approve` and `Approve Publisher` against
# Type=publisher for the same intent — the legacy VBA wrote the publisher name
# with Type=publisher whichever button was pressed. Both mean approve-publisher.
_TITLE_DECISIONS = {
    "approve": SoftwareDecision.Decision.APPROVE,
    "reject": SoftwareDecision.Decision.REJECT,
    "investigate": SoftwareDecision.Decision.INVESTIGATE,
}
_PUBLISHER_DECISIONS = {
    "approve": SoftwareDecision.Decision.APPROVE_PUBLISHER,
    "approve publisher": SoftwareDecision.Decision.APPROVE_PUBLISHER,
    "reject": SoftwareDecision.Decision.REJECT,
    "investigate": SoftwareDecision.Decision.INVESTIGATE,
}


class Command(BaseCommand):
    help = "Import software decisions from a legacy decisions CSV (dry run by default)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--file", required=True, help="Path to decisions_*.csv")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command only reports.",
        )
        parser.add_argument("--tenant", type=int, default=1)

    def handle(self, *args, **options) -> None:
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"no such file: {path}")

        actor = (
            get_user_model().objects.filter(is_superuser=True).order_by("id").first()
            or get_user_model().objects.order_by("id").first()
        )
        if actor is None:
            raise CommandError("no user exists to attribute the decisions to")

        tenant_id = options["tenant"]
        parsed, unmapped = self._parse(path)

        create, update, skip_operator, unchanged = [], [], [], []
        for canonical_name, publisher, decision in parsed:
            lookup = {"tenant_id": tenant_id, "client_id": None, "device_id": None}
            if canonical_name:
                lookup["canonical_name"] = canonical_name
            else:
                lookup["publisher"] = publisher
            existing = SoftwareDecision.objects.filter(**lookup).first()
            if existing is None:
                create.append((canonical_name, publisher, decision))
            elif existing.reason != IMPORT_REASON:
                skip_operator.append((canonical_name or publisher, existing.decision))
            elif existing.decision != decision:
                update.append((existing, decision))
            else:
                unchanged.append(existing)

        self.stdout.write(
            f"corpus rows parsed : {len(parsed)}  (unmapped skipped: {len(unmapped)})"
        )
        self.stdout.write(f"  to create        : {len(create)}")
        self.stdout.write(f"  to update        : {len(update)}")
        self.stdout.write(f"  already correct  : {len(unchanged)}")
        self.stdout.write(f"  operator-owned   : {len(skip_operator)}  (never overwritten)")
        for name, value in unmapped[:10]:
            self.stdout.write(self.style.WARNING(f"  unmapped: {name!r} -> {value!r}"))

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("dry run — nothing written. Re-run with --apply."))
            return

        now = timezone.now()
        with transaction.atomic():
            SoftwareDecision.objects.bulk_create(
                [
                    SoftwareDecision(
                        tenant_id=tenant_id,
                        client_id=None,
                        device_id=None,
                        canonical_name=canonical_name,
                        publisher=publisher,
                        decision=decision,
                        reason=IMPORT_REASON,
                        decided_by=actor,
                        decided_at=now,
                    )
                    for canonical_name, publisher, decision in create
                ]
            )
            for existing, decision in update:
                existing.decision = decision
                existing.save(update_fields=["decision"])

        self.stdout.write(
            self.style.SUCCESS(
                f"applied: created={len(create)} updated={len(update)} "
                f"untouched={len(unchanged) + len(skip_operator)}"
            )
        )

    def _parse(self, path: Path) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
        """Return (rows, unmapped). First occurrence wins on duplicate keys."""
        rows: list[tuple[str, str, str]] = []
        unmapped: list[tuple[str, str]] = []
        seen_titles: set[str] = set()
        seen_publishers: set[str] = set()

        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                name = (raw.get("Name") or "").strip()
                decision = (raw.get("Decision") or "").strip()
                kind = (raw.get("Type") or "").strip().lower()
                if not name or not decision:
                    continue
                if kind == "publisher":
                    mapped = _PUBLISHER_DECISIONS.get(decision.lower())
                    if mapped is None:
                        unmapped.append((name, decision))
                        continue
                    key = name.lower()
                    if key in seen_publishers:
                        continue
                    seen_publishers.add(key)
                    rows.append(("", name, mapped))
                else:
                    mapped = _TITLE_DECISIONS.get(decision.lower())
                    if mapped is None:
                        unmapped.append((name, decision))
                        continue
                    key = name.lower()
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    rows.append((name, "", mapped))
        return rows, unmapped
