"""Migration 0135 -- `install_path_suspicious` moves onto the installation.

ADR-0015 s2 assigns three subject kinds, and one was never implemented:

    "**Installation facts** -- `install_path_suspicious`. The path belongs to
     the device-and-software pair, so the finding belongs to the
     **relationship**."

Migration 0130 left it on `device` and its docstring recorded the reason as
"ADR-0015 keeps the first two on device explicitly". That is correct for
`rare_recent` -- recency genuinely is a per-device fact -- but wrong for
`install_path_suspicious`, which the ADR places on the relationship in the
sentence quoted above. `.work/plan.md` carried the same mistaken reading, so
step 3 moved eight types and left this one behind with nothing recording that
an Accepted ADR had been overruled.

Subject identity is `software_installations_current.installation_uuid`, minted
by SQL migration 089. Minted rather than derived, and the case is stronger than
076's: the installation primary key is
`(tenant_id, client_id, device_id, canonical_name)` and EXCLUDES the version,
so an upgrade updates the row in place. A subject derived from
`(device_id, version_uuid)` would change on every software update and reopen
the finding while the install path never moved.

`multi_av_conflict` and `rare_recent` stay on device and are untouched.

Reversible: the scope returns to `device` and the subject type choice is
restored. The closed rows are not reopened on reverse -- reopening a resolved
finding would fabricate operator state, and the classifier re-emits within one
scheduled cycle either way.
"""

from typing import ClassVar

from django.db import migrations, models

_CLOSE_SUPERSEDED = """
UPDATE operations.findings f
   SET status    = 'resolved',
       closed_at = COALESCE(f.closed_at, now()),
       finding_details = f.finding_details || jsonb_build_object(
           'resolution', jsonb_build_object(
               'reason', 'resubjected_to_installation_scope',
               'detail', 'Superseded by a finding on the installation, i.e. '
                      || 'the device-and-software pair (ADR-0015 s2). The '
                      || 'condition was not remediated; only the subject it '
                      || 'is recorded against changed.',
               'previous_subject_type', f.subject_type,
               'previous_subject_id',   f.subject_id,
               'migration', '0135',
               'closed_at', to_char(now() AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"')
           )
       )
  FROM operations.finding_types ft
 WHERE ft.id = f.finding_type_id
   AND ft.name = 'install_path_suspicious'
   AND f.subject_type = 'device'
   AND f.status IN ('open', 'acknowledged');
"""


def set_scope(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="install_path_suspicious").update(
        subject_scope="software_installation"
    )


def unset_scope(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    FindingType.objects.filter(name="install_path_suspicious").update(
        subject_scope="device"
    )


def noop(apps, schema_editor):
    """Deliberately does not reopen the closed rows -- see the module docstring."""


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0134_windows_servicing_lifecycle"),
    ]

    operations: ClassVar[list] = [
        migrations.AlterField(
            model_name="finding",
            name="subject_type",
            field=models.CharField(
                choices=[
                    ("client", "Client"),
                    ("device", "Device"),
                    ("client_user", "Client user"),
                    ("source_binding", "Source binding"),
                    ("collector_instance", "Collector instance"),
                    ("software_product", "Software product"),
                    ("software_version", "Software version"),
                    ("software_installation", "Software installation"),
                ],
                max_length=32,
            ),
        ),
        # Order matters: close the superseded rows *before* the scope flips, so
        # the classifier cannot emit at the new subject and find the old rows
        # still open under a condition key it no longer produces.
        migrations.RunSQL(_CLOSE_SUPERSEDED, migrations.RunSQL.noop),
        migrations.RunPython(set_scope, unset_scope),
        migrations.RunPython(noop, noop),
    ]
