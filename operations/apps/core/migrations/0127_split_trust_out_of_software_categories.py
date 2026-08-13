"""Migration 0127 — move software trust labels out of `categories` (ADR-0015 §3).

`software_catalog.categories` carried two unrelated kinds of label:

* **functional** — `av`, `remote_access`, `rmm`: what the software *does*,
  resolved against `RequirementProfile` to produce `unauthorized_av` and
  `unauthorized_remote_access`;
* **trust** — `whitelist`, `trusted_publisher`: whether we *trust* it.

In the legacy analyzer these were separate lists (`WHITELIST`,
`TRUSTED_PUBLISHERS`) with no relation to any category. The port merged them
into one array, and the conflation became load-bearing: `whitelist_suggestion`
fired on `not cat_list`, so labelling a title `av` — a statement carrying no
judgement — silenced the decision prompt exactly as a trust label did.

Trust is a decision. `software_decisions` already models it at title and
publisher scope with scoping, audit and an operator surface, so this migration
moves the twelve trust rows there and strips the labels from the catalog.

Measured before the move:

* 5 `whitelist` rows — real titles (7-Zip, Google Chrome, Microsoft Edge,
  Mozilla Firefox, Notepad++). None had a decision. All become
  title-scope `approve`.
* 7 `trusted_publisher` rows — these hold a *publisher* name in
  `canonical_name` (Adobe Inc., Apple Inc., Cisco Systems, Google LLC,
  Microsoft Corporation, Mozilla, Zoom Video Communications) with the
  publisher in `publisher_hint`. Three (Adobe Inc., Microsoft Corporation,
  Mozilla) already had a publisher decision from the corpus import and are
  left alone; the other four become publisher-scope `approve_publisher`.
* No row carried both a trust and a functional label, so nothing is ambiguous.

Net: 9 decisions created, 12 catalog rows stripped of trust labels. Rows left
with an empty `categories` array are kept — `publisher_hint` and `eol_date`
are still theirs to carry.

**40 functional-only titles stop being suppressed** and will surface for
decision on the next classifier run. That is the intended correction: nobody
ever decided them, and a functional label was never a decision.

Idempotent: a decision is only created where one does not already exist for
that scope and key, and it never overwrites an operator's own row.
"""

from typing import ClassVar

from django.db import migrations

TRUST_LABELS = ("whitelist", "trusted_publisher")
MOVE_REASON = "migrated from software_catalog trust category (ADR-0015 §3)"


def split_trust(apps, schema_editor):
    SoftwareCatalog = apps.get_model("operations", "SoftwareCatalog")
    SoftwareDecision = apps.get_model("operations", "SoftwareDecision")
    User = apps.get_model("operations", "User")

    actor = (
        User.objects.filter(is_superuser=True).order_by("id").first()
        or User.objects.order_by("id").first()
    )
    if actor is None:
        print("[0127] no user to attribute decisions to; leaving catalog untouched")
        return

    created = existing = 0
    for entry in SoftwareCatalog.objects.all():
        labels = list(entry.categories or [])
        trust = [label for label in labels if label in TRUST_LABELS]
        if not trust:
            continue

        # `trusted_publisher` rows name a publisher; `whitelist` rows a title.
        if "trusted_publisher" in trust:
            lookup = {"publisher__iexact": entry.canonical_name}
            fields = {"publisher": entry.canonical_name, "canonical_name": ""}
            decision = "approve_publisher"
        else:
            lookup = {"canonical_name__iexact": entry.canonical_name}
            fields = {"canonical_name": entry.canonical_name, "publisher": ""}
            decision = "approve"

        already = SoftwareDecision.objects.filter(
            tenant_id=1, client_id=None, device_id=None, **lookup
        ).exists()
        if already:
            existing += 1
        else:
            SoftwareDecision.objects.create(
                tenant_id=1,
                client_id=None,
                device_id=None,
                decision=decision,
                reason=MOVE_REASON,
                decided_by=actor,
                decided_at=entry.__dict__.get("created_at") or None,
                version=1,
                **fields,
            )
            created += 1

        entry.categories = [label for label in labels if label not in TRUST_LABELS]
        entry.save(update_fields=["categories"])

    print(
        f"[0127] trust split from catalog: decisions_created={created} "
        f"already_decided={existing}"
    )


def restore_trust(apps, schema_editor):
    """Put the labels back and remove only the decisions this migration made."""
    SoftwareCatalog = apps.get_model("operations", "SoftwareCatalog")
    SoftwareDecision = apps.get_model("operations", "SoftwareDecision")

    moved = SoftwareDecision.objects.filter(tenant_id=1, reason=MOVE_REASON)
    for decision in moved:
        name = decision.publisher or decision.canonical_name
        label = "trusted_publisher" if decision.publisher else "whitelist"
        entry = SoftwareCatalog.objects.filter(canonical_name__iexact=name).first()
        if entry is not None:
            labels = list(entry.categories or [])
            if label not in labels:
                labels.append(label)
                entry.categories = labels
                entry.save(update_fields=["categories"])
    removed = moved.delete()
    print(f"[0127] trust restored to catalog; decisions removed: {removed}")


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0126_software_page_indexes"),
    ]

    operations: ClassVar = [
        migrations.RunPython(split_trust, restore_trust),
    ]
