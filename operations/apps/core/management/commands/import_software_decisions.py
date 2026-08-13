"""Import operator software decisions from a legacy `decisions_*.csv`.

The legacy analyzer accumulated its decisions in `decisions_global.csv` and
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
    cat decisions_global.csv | python manage.py import_software_decisions --file -

Pass ``--file -`` to read the CSV from stdin, which lets the corpus be piped
straight into the container over ssh without ever landing on the host:

    Get-Content corpus.csv | <helper> ssh
        'docker exec -i ninja-operations python manage.py
         import_software_decisions --file - --apply'

Dry run by default: it reports exactly what would change and writes nothing.

Sets the tenant GUC before it queries: `operations.users` and
`software_decisions` carry forced RLS, and a management command runs outside
the request cycle where middleware would normally set it.

Idempotent and non-destructive. Global-scope uniqueness is
`(tenant, canonical_name)` and `(tenant, publisher)`, so a re-run updates
rather than duplicates. A row an operator has since changed in the UI is never
overwritten — the import only touches rows it created itself, identified by
`reason`.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
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
        parser.add_argument(
            "--file",
            required=True,
            help="Path to decisions_*.csv, or '-' to read the CSV from stdin.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command only reports.",
        )
        parser.add_argument("--tenant", type=int, default=1)

    def handle(self, *args, **options) -> None:
        text = self._read(options["file"])
        tenant_id = options["tenant"]
        # operations.users and software_decisions both carry forced RLS with a
        # tenant policy. A management command runs outside the request cycle,
        # so nothing has set the GUC and every query returns zero rows — which
        # surfaces as "no user exists to attribute the decisions to" rather
        # than as a permission error.
        self._set_tenant(tenant_id)
        actor = self._actor()

        parsed, unmapped = self._parse(text)
        plan = self._plan(parsed, tenant_id)

        self.stdout.write(
            f"corpus rows parsed : {len(parsed)}  (unmapped skipped: {len(unmapped)})"
        )
        self.stdout.write(f"  to create        : {len(plan['create'])}")
        self.stdout.write(f"  to update        : {len(plan['update'])}")
        self.stdout.write(f"  already correct  : {plan['unchanged']}")
        self.stdout.write(
            f"  operator-owned   : {plan['operator_owned']}  (never overwritten)"
        )
        for name, value in unmapped[:10]:
            self.stdout.write(self.style.WARNING(f"  unmapped: {name!r} -> {value!r}"))

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("dry run — nothing written. Re-run with --apply.")
            )
            return

        self._write(plan, tenant_id, actor)
        self.stdout.write(
            self.style.SUCCESS(
                f"applied: created={len(plan['create'])} updated={len(plan['update'])} "
                f"untouched={plan['unchanged'] + plan['operator_owned']}"
            )
        )

    def _set_tenant(self, tenant_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('operations.tenant_id', %s, false)", [str(tenant_id)])

    def _read(self, source: str) -> str:
        if source == "-":
            text = sys.stdin.read()
            if not text.strip():
                raise CommandError("no CSV received on stdin")
            return text
        path = Path(source)
        if not path.is_file():
            raise CommandError(f"no such file: {path}")
        return path.read_text(encoding="utf-8-sig")

    def _actor(self):
        users = get_user_model().objects
        actor = users.filter(is_superuser=True).order_by("id").first() or users.order_by("id").first()
        if actor is None:
            raise CommandError("no user exists to attribute the decisions to")
        return actor

    def _plan(self, parsed, tenant_id: int) -> dict:
        """Classify each corpus row against what is already stored."""
        create, update, unchanged, operator_owned = [], [], 0, 0
        for canonical_name, publisher, decision in parsed:
            lookup = {"tenant_id": tenant_id, "client_id": None, "device_id": None}
            lookup["canonical_name" if canonical_name else "publisher"] = (
                canonical_name or publisher
            )
            existing = SoftwareDecision.objects.filter(**lookup).first()
            if existing is None:
                create.append((canonical_name, publisher, decision))
            elif existing.reason != IMPORT_REASON:
                operator_owned += 1          # never overwrite a human's own edit
            elif existing.decision != decision:
                update.append((existing, decision))
            else:
                unchanged += 1
        return {
            "create": create,
            "update": update,
            "unchanged": unchanged,
            "operator_owned": operator_owned,
        }

    def _write(self, plan: dict, tenant_id: int, actor) -> None:
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
                    for canonical_name, publisher, decision in plan["create"]
                ]
            )
            for existing, decision in plan["update"]:
                existing.decision = decision
                existing.save(update_fields=["decision"])

    def _parse(self, text: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
        """Return (rows, unmapped). First occurrence wins on duplicate keys."""
        rows: list[tuple[str, str, str]] = []
        unmapped: list[tuple[str, str]] = []
        seen: dict[str, set[str]] = {"publisher": set(), "title": set()}

        for raw in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            name = (raw.get("Name") or "").strip()
            decision = (raw.get("Decision") or "").strip()
            kind = "publisher" if (raw.get("Type") or "").strip().lower() == "publisher" else "title"
            if not name or not decision:
                continue

            table = _PUBLISHER_DECISIONS if kind == "publisher" else _TITLE_DECISIONS
            mapped = table.get(decision.lower())
            if mapped is None:
                unmapped.append((name, decision))
                continue

            key = name.lower()
            if key in seen[kind]:
                continue
            seen[kind].add(key)
            rows.append(("", name, mapped) if kind == "publisher" else (name, "", mapped))

        return rows, unmapped
