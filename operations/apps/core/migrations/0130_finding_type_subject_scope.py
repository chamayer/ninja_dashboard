"""Migration 0130 -- what a finding type is *about* becomes a registry row.

The software classifier emits nine finding types and they are not all about the
same thing. Seven assert something intrinsic to the software; two assert
something about the machine. Until now the emitter hardcoded `'device'` for all
nine, which is why 134,484 rows exist where ~1,831 subjects would do.

Putting the scope in the emitter as a Python dict was the obvious alternative
and is the wrong one twice over: ADR-0012 section 6 requires a mapping from one
domain value to another to be operator-maintainable data, and
`ingest/tests/test_no_hardcoded_domain_mappings.py` is a ratchet that fails on
exactly that shape.

Scopes assigned below, from the measurement of 2026-08-10:

  software_product -- whitelist_suggestion, suspicious_name,
      unauthorized_av, unauthorized_rmm, unauthorized_remote_access,
      known_malicious_hint.
      "Is this title allowed here" does not change with the release.
      unauthorized_rmm is included with its two siblings: all three come from
      the same sanctioned-category rule, and scoping them differently would be
      an inconsistency with no cause behind it.

  software_version -- vulnerable_software, eol_runtime.
      A CVE applies to a version range; an EOL date belongs to a release. At
      title scope a patched install is indistinguishable from an unpatched one,
      which is fatal for the two findings whose remedy is patching
      (ADR-0008 amendment 2026-08-06; ADR-0012 s5 governs).

  device (unchanged, left at the column default) -- rare_recent,
      install_path_suspicious, multi_av_conflict.
      Recency, install path and "two AV products on this machine" are genuinely
      per-device facts. ADR-0015 keeps the first two on device explicitly.

Data only for rows that exist; a fresh install seeds its own finding types and
picks these up by name. Reversible.
"""

from django.db import migrations, models

_PRODUCT_SCOPED = (
    "whitelist_suggestion",
    "suspicious_name",
    "unauthorized_av",
    "unauthorized_rmm",
    "unauthorized_remote_access",
    "known_malicious_hint",
)

_VERSION_SCOPED = (
    "vulnerable_software",
    "eol_runtime",
)


def set_scopes(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name__in=_PRODUCT_SCOPED).update(
        subject_scope="software_product"
    )
    FindingType.objects.filter(name__in=_VERSION_SCOPED).update(
        subject_scope="software_version"
    )


def unset_scopes(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(
        name__in=_PRODUCT_SCOPED + _VERSION_SCOPED
    ).update(subject_scope="device")


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0129_software_finding_subject_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='findingtype',
            name='subject_scope',
            field=models.CharField(
                choices=[
                    ('device', 'This device'),
                    ('software_product', 'The software title'),
                    ('software_version', 'The software release'),
                ],
                default='device',
                max_length=24,
            ),
        ),
        migrations.RunPython(set_scopes, unset_scopes),
    ]
