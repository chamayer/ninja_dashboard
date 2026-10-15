"""One registry for every finding type: name, category, group, order, and what covers it.

``finding_types`` becomes the single place a finding's presentation and cover
rules are configured:

- ``display_name``: the one name used on every screen (required, unique).
- ``issue_category`` and ``issue_group``: the five categories and 17 groups of the
  Issues page. Plain text on purpose; the Finding types page offers the existing
  values and a test keeps each group inside one category.
- ``sort_order``: category and group order follow their first type.
- ``covered_by`` and ``cover_note``: the parent types that make this finding
  redundant on the same computer. A database check stops a type covering itself.

The older seven-row ``finding_categories`` table and ``finding_types.category``
are removed; their readers use ``issue_category``.
"""

from typing import ClassVar

from django.db import migrations, models

# (type, display name, category, group, order, covered by, note). Reviewed 2026-10-15.
ROWS = (
    ('device_source_record_withdrawn', 'Computer no longer reported by a source', 'Inventory', 'Computers no source reports', 10, ['device_missing_from_source'], 'Each withdrawn source record is evidence for the computer no source reports.'),
    ('device_missing_from_source', 'Computer not reported by any source', 'Inventory', 'Computers no source reports', 20, [], ''),
    ('identity_conflict', 'Possible duplicate computers', 'Inventory', 'Duplicate computers', 30, [], ''),
    ('duplicate_platform_record', 'Duplicate entries in one platform', 'Inventory', 'Duplicate computers', 40, [], ''),
    ('duplicate_device_records', 'Duplicate Hudu entries (historical)', 'Inventory', 'Duplicate computers', 50, [], ''),
    ('cross_client_conflict', 'Same hostname on two clients', 'Inventory', 'Duplicate computers', 60, [], ''),
    ('shared_serial', 'Shared identifier', 'Inventory', 'Computer identity', 70, [], ''),
    ('cross_client_serial', 'Shared identifier across clients', 'Inventory', 'Computer identity', 80, [], ''),
    ('placeholder_serial', 'Placeholder serial number', 'Inventory', 'Computer identity', 90, [], ''),
    ('placeholder_mac', 'Placeholder MAC address', 'Inventory', 'Computer identity', 100, [], ''),
    ('identity_resolution_pending', 'Awaiting computer identity match', 'Inventory', 'Computer identity', 110, [], ''),
    ('unlinked_external_identity', 'Unresolved computer from source', 'Inventory', 'Computer identity', 120, [], ''),
    ('device_role_conflict', 'Computer role changed', 'Inventory', 'Computer details', 130, [], ''),
    ('lifecycle_reported_state_conflict', 'Platforms disagree on lifecycle status', 'Inventory', 'Computer details', 140, [], ''),
    ('lifecycle_unknown_reported_state', 'Unknown lifecycle status', 'Inventory', 'Computer details', 150, [], ''),
    ('unmapped_node_class', 'Unrecognized computer type', 'Inventory', 'Computer details', 160, [], ''),
    ('client_name_conflict', 'Client renamed at source', 'Inventory', 'Client mapping', 170, [], ''),
    ('client_link_collision', 'Multiple clients claim this name', 'Inventory', 'Client mapping', 180, [], ''),
    ('client_source_group_merge', 'Duplicate source groups mapped to one client', 'Inventory', 'Client mapping', 190, [], ''),
    ('client_unattached_group', 'Group not attached to a client', 'Inventory', 'Client mapping', 200, [], ''),
    ('unnamed_source_group', 'Unnamed platform organization', 'Inventory', 'Client mapping', 210, [], ''),
    ('unmatched_source_group', 'Platform group awaiting matching', 'Inventory', 'Client mapping', 220, [], ''),
    ('cmdb_asset_stale', 'Hudu archive candidate', 'Inventory', 'Hudu records', 230, [], ''),
    ('cmdb_link_incorrect', 'Hudu record linked to different Computers', 'Inventory', 'Hudu records', 240, [], ''),
    ('unintegrated_source_observed', 'Hudu references an unconnected platform', 'Inventory', 'Hudu records', 250, [], ''),
    ('missing_required_platform', 'Required agent not installed', 'Agents & reporting', 'Required agents', 260, ['device_missing_from_source'], 'Agent coverage cannot be assessed on a computer no source reports.'),
    ('device_unenrolled', 'No management agent installed', 'Agents & reporting', 'Required agents', 270, [], ''),
    ('stale_required_platform', 'Required agent not checking in', 'Agents & reporting', 'Required agents', 280, ['device_offline', 'device_missing_from_source'], 'A stale agent is expected on a computer that is offline or that no source reports.'),
    ('device_offline', 'Computer offline', 'Agents & reporting', 'Computers offline', 290, ['device_missing_from_source'], 'No source reports the computer, so being offline is part of the same fact.'),
    ('device_long_offline', 'Offline for an extended period', 'Agents & reporting', 'Computers offline', 300, [], ''),
    ('device_stale_data', 'No recent data', 'Agents & reporting', 'Computers offline', 310, [], ''),
    ('rare_recent', 'Rare software', 'Software & security', 'Software approval', 320, [], ''),
    ('whitelist_suggestion', 'Widespread software without a decision', 'Software & security', 'Software approval', 330, [], ''),
    ('capability_review_candidate', 'Software capability not confirmed', 'Software & security', 'Software classification', 340, [], ''),
    ('unauthorized_remote_access', 'Unauthorized remote access tool', 'Software & security', 'Unapproved software', 350, [], ''),
    ('unauthorized_rmm', 'Unauthorized RMM tool', 'Software & security', 'Unapproved software', 360, [], ''),
    ('unauthorized_av', 'Unauthorized AV product', 'Software & security', 'Unapproved software', 370, [], ''),
    ('multi_av_conflict', 'Multiple AV products installed', 'Software & security', 'Unapproved software', 380, [], ''),
    ('rejected_software_installed', 'Rejected software installed', 'Software & security', 'Unapproved software', 390, [], ''),
    ('suspicious_name', 'Suspicious name', 'Software & security', 'Suspicious software', 400, [], ''),
    ('install_path_suspicious', 'Installed from suspicious location', 'Software & security', 'Suspicious software', 410, [], ''),
    ('known_malicious_hint', 'Software matches threat-report indicators', 'Software & security', 'Suspicious software', 420, [], ''),
    ('vulnerable_software', 'Software vulnerability detected', 'Software & security', 'Vulnerable & unsupported software', 430, [], ''),
    ('eol_runtime', 'End-of-life runtime', 'Software & security', 'Vulnerable & unsupported software', 440, [], ''),
    ('device_never_patched', 'No patch installed yet', 'Patching & support', 'Patching', 450, [], ''),
    ('patching_stalled', 'No recent patch activity', 'Patching & support', 'Patching', 460, ['device_offline', 'device_missing_from_source'], 'Patching cannot progress on a computer that is offline or that no source reports.'),
    ('patch_approval_backlog', 'Approved updates not installed', 'Patching & support', 'Patching', 470, [], ''),
    ('patch_failing_repeatedly', 'Update repeatedly failing', 'Patching & support', 'Patching', 480, [], ''),
    ('reboot_pending', 'Restart required', 'Patching & support', 'Patching', 490, ['device_offline', 'device_missing_from_source', 'patching_stalled'], 'A restart cannot happen while the computer is offline, unreported, or its patching is stalled.'),
    ('windows_servicing_approaching_eol', 'Windows support ending soon', 'Patching & support', 'Windows support', 500, [], ''),
    ('windows_servicing_eol', 'Windows build out of support', 'Patching & support', 'Windows support', 510, [], ''),
    ('windows_servicing_unknown', 'Windows support state unknown', 'Patching & support', 'Windows support', 520, ['device_missing_from_source', 'missing_required_platform'], 'The Windows support state cannot be read without a source or the required agent.'),
    ('source_failure', 'Data source not responding', 'Data collection', 'Collection and processing', 530, [], ''),
    ('software_queue_stalled', 'Software scan queue stalled', 'Data collection', 'Collection and processing', 540, [], ''),
    ('stale_collector_binding', 'Ingest connector stopped', 'Data collection', 'Collection and processing', 550, [], ''),
    ('software_inventory_held', 'Software list held for review', 'Data collection', 'Collection and processing', 560, [], ''),
    ('jobs_schedule_failure', 'Scheduled Job failed', 'Data collection', 'Jobs control plane', 570, [], ''),
    ('jobs_required_disabled', 'Required Job is disabled', 'Data collection', 'Jobs control plane', 580, [], ''),
    ('jobs_queue_backlog', 'Jobs queue delayed', 'Data collection', 'Jobs control plane', 590, [], ''),
    ('jobs_repeated_failure', 'Job fails repeatedly', 'Data collection', 'Jobs control plane', 600, [], ''),
    ('jobs_timeout', 'Job timed out', 'Data collection', 'Jobs control plane', 610, [], ''),
    ('jobs_registry_mismatch', 'Jobs registry mismatch', 'Data collection', 'Jobs control plane', 620, [], ''),
    ('jobs_unmet_dependency', 'Job dependency is unmet', 'Data collection', 'Jobs control plane', 630, [], ''),
)


def seed(apps, schema_editor):
    finding_type = apps.get_model("operations", "FindingType")
    known = {row[0]: row for row in ROWS}
    for index, row in enumerate(finding_type.objects.order_by("name")):
        entry = known.get(row.name)
        if entry is None:
            # A type this migration does not know (a development database): keep it usable.
            row.display_name = row.name.replace("_", " ").capitalize()
            row.issue_category = "Other"
            row.issue_group = "Other"
            row.sort_order = 10_000 + index
        else:
            _name, display, category, group, order, covered, note = entry
            row.display_name = display
            row.issue_category = category
            row.issue_group = group
            row.sort_order = order
            row.covered_by = covered
            row.cover_note = note
        row.save(
            update_fields=[
                "display_name", "issue_category", "issue_group", "sort_order",
                "covered_by", "cover_note",
            ]
        )


CONSTRAINTS_SQL = """
ALTER TABLE operations.finding_types
    ADD CONSTRAINT ck_finding_type_covered_by_list CHECK (jsonb_typeof(covered_by) = 'array'),
    ADD CONSTRAINT ck_finding_type_not_self_covered CHECK (NOT (covered_by ? name)),
    ADD CONSTRAINT ck_finding_type_registry_filled CHECK (
        display_name <> '' AND issue_category <> '' AND issue_group <> '');
"""

DROP_CONSTRAINTS_SQL = """
ALTER TABLE operations.finding_types
    DROP CONSTRAINT IF EXISTS ck_finding_type_registry_filled,
    DROP CONSTRAINT IF EXISTS ck_finding_type_not_self_covered,
    DROP CONSTRAINT IF EXISTS ck_finding_type_covered_by_list;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0294_client_offline_after_days"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="findingtype",
            name="display_name",
            field=models.CharField(max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="issue_category",
            field=models.CharField(default="", max_length=40),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="issue_group",
            field=models.CharField(default="", max_length=80),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="sort_order",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="covered_by",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="findingtype",
            name="cover_note",
            field=models.CharField(blank=True, default="", max_length=240),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="findingtype",
            name="display_name",
            field=models.CharField(max_length=120, unique=True),
        ),
        migrations.AlterField(
            model_name="findingtype",
            name="issue_category",
            field=models.CharField(max_length=40),
        ),
        migrations.AlterField(
            model_name="findingtype",
            name="issue_group",
            field=models.CharField(max_length=80),
        ),
        migrations.RunSQL(CONSTRAINTS_SQL, DROP_CONSTRAINTS_SQL),
        migrations.RemoveField(model_name="findingtype", name="category"),
        migrations.DeleteModel(name="FindingCategory"),
    ]
