"""Add ``finding_types.alertable`` and seed the types that may notify.

Default is off. Only a specific, actionable problem in a client environment or
in a failing platform function may notify; decisions, mappings, identity and
symptom types never do. Rules and routes still decide where a finding goes.
The notifier and digest read this flag (ingest/notification_scope.py).
"""

from typing import ClassVar

from django.db import migrations, models

ALERTABLE_TYPES = (
    "missing_required_platform",
    "stale_required_platform",
    "device_unenrolled",
    "patch_failing_repeatedly",
    "device_never_patched",
    "patch_approval_backlog",
    "windows_servicing_eol",
    "vulnerable_software",
    "eol_runtime",
    "install_path_suspicious",
    "rejected_software_installed",
    "unauthorized_av",
    "unauthorized_remote_access",
    "unauthorized_rmm",
    "source_failure",
    "jobs_schedule_failure",
    "jobs_timeout",
    "jobs_repeated_failure",
    "jobs_required_disabled",
    "jobs_queue_backlog",
    "jobs_registry_mismatch",
)

_names = ", ".join(f"'{n}'" for n in ALERTABLE_TYPES)
FORWARD_SQL = f"""
UPDATE operations.finding_types SET alertable = TRUE WHERE name IN ({_names});
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0290_device_last_user_read_model"),
    ]
    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="findingtype",
            name="alertable",
            field=models.BooleanField(
                default=False,
                help_text="Checked when a finding of this type may produce an alert or a digest line. Notification rules only apply to checked types.",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
