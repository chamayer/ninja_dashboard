"""Persist the installation state last reconciled by the software classifier."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS classifier_material_hash BYTEA,
    ADD COLUMN IF NOT EXISTS classifier_active BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_software_installations_classifier_pending
    ON operations.software_installations_current (tenant_id, device_id)
    WHERE classifier_material_hash IS NULL;
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS operations.idx_software_installations_classifier_pending;
ALTER TABLE operations.software_installations_current
    DROP COLUMN IF EXISTS classifier_active,
    DROP COLUMN IF EXISTS classifier_material_hash;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0180_operator_job_workflow_controls"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
