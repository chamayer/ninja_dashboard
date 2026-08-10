"""Migration 0129 -- software becomes a finding subject, at two granularities.

Every existing `Finding.SubjectType` names an owned entity with a uuid primary
key in `operations.entities`. Software is the first subject that is not owned:
per the ADR-0012 amendment of 2026-08-10 it is global reference data beside
`intel.cves`, carrying no tenant and no scope_kind. `subject_id` stays a bare
uuid with no foreign key -- the subject has always been polymorphic -- and now
holds `catalog.products.product_uuid` or
`catalog.software_versions.version_uuid`, added by SQL migration 076.

**Two types, not one.** Granularity differs by finding type, and measurement
2026-08-10 shows the difference is real:

  * Five types assert something about the *title* -- whitelist_suggestion,
    suspicious_name, unauthorized_remote_access, unauthorized_av,
    known_malicious_hint. "Is this software allowed here" does not change with
    the release.
  * Two assert something about the *release* -- vulnerable_software and
    eol_runtime. A CVE applies to a version range and an EOL date is a
    release's. At title scope these collapse 1,403 -> 17 and 630 -> 106; at
    product+version they are 54 and 123.

Collapsing both into one `software` type would make a patched install
indistinguishable from an unpatched one, which is fatal for precisely the two
findings whose remedy is patching (ADR-0008 amendment 2026-08-06).

Choices-only field alteration: no table rewrite, no data migration. Existing
rows keep `subject_type='device'` until the emitter change re-subjects them and
closes them with a recorded cause.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0128_candidate_source_layout_read_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='finding',
            name='subject_type',
            field=models.CharField(choices=[('client', 'Client'), ('device', 'Device'), ('client_user', 'Client user'), ('source_binding', 'Source binding'), ('collector_instance', 'Collector instance'), ('software_product', 'Software product'), ('software_version', 'Software version')], max_length=32),
        ),
    ]
