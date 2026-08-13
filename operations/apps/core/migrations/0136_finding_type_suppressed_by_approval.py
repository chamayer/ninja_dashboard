"""Migration 0136 -- approval stops silencing facts.

`ingest/software_findings.py` skipped every rule for an approved installation at
the top of its loop:

    dec = _resolve_decision(...)
    if dec in ("approve", "approve_publisher"):
        continue  # approved, skip all rules

So approving a title also silenced its vulnerabilities, its threat-intel hits,
its end-of-life state and its suspicious install path. `vulnerable_software` and
`known_malicious_hint` additionally re-tested the decision locally, so they were
suppressed twice over.

Approval means "this software is allowed here". That is a statement about
**trust**, and it cannot make a CVE untrue. Which findings a trust decision may
silence is therefore a per-type property, and it belongs in the registry beside
`subject_scope` rather than in a module-level dict in the emitter -- ADR-0012
section 6, and the shape `test_no_hardcoded_domain_mappings` exists to catch.

The matrix:

  suppressed (a trust question)
    unauthorized_av / _rmm / _remote_access -- approval IS the policy exception
    whitelist_suggestion -- it exists to request a decision
    suspicious_name      -- a trust heuristic
    rare_recent          -- defined as "recent AND rare AND undecided"; its own
                            rare_recent_skip_decided gate already says so
    multi_av_conflict    -- unchanged here; disabled separately

  NOT suppressed (a fact about the software)
    vulnerable_software
    known_malicious_hint
    eol_runtime
    install_path_suspicious

Also declares SubjectScope.SOFTWARE_INSTALLATION. Migration 0135 set
install_path_suspicious to that scope without adding it to the model's choices,
leaving the registry holding a value the model rejected.

Data only for rows that exist; a fresh install seeds its own finding types and
picks the default up. Reversible: the column drops and behavior returns to the
blanket skip.
"""

from typing import ClassVar

from django.db import migrations, models

# Findings that assert a fact about the software. Trust cannot make them untrue.
_FACTUAL = (
    "vulnerable_software",
    "known_malicious_hint",
    "eol_runtime",
    "install_path_suspicious",
)


def set_matrix(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    # Everything defaults to True (previous behavior). Only the factual types
    # are opened up, so no finding starts firing that was not already firing
    # for undecided software.
    FindingType.objects.filter(name__in=_FACTUAL).update(suppressed_by_approval=False)


def unset_matrix(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name__in=_FACTUAL).update(suppressed_by_approval=True)


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0135_software_installation_subject"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="findingtype",
            name="suppressed_by_approval",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When checked, an approve decision on the software silences "
                    "this finding. Leave unchecked for findings that state a "
                    "fact about the software (vulnerability, malicious intel, "
                    "end-of-life, install path) -- approving software does not "
                    "make those untrue."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="findingtype",
            name="subject_scope",
            field=models.CharField(
                choices=[
                    ("device", "This device"),
                    ("software_product", "The software title"),
                    ("software_version", "The software release"),
                    ("software_installation", "The installation"),
                ],
                default="device",
                max_length=24,
            ),
        ),
        migrations.RunPython(set_matrix, unset_matrix),
    ]
