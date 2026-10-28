"""Permit explicit state only when a Computer has no qualified direct contact.

Only the remote-access and monitoring entity types opt in. Existing hybrid
evidence policy, observation data and finding history remain unchanged.
"""

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = """
DO $fallback$
BEGIN
    IF (SELECT count(*) FROM operations.entity_types
        WHERE name IN ('agent.remote_access','agent.monitoring')
          AND lifecycle_evidence_mode='direct_contact') <> 2 THEN
        RAISE EXCEPTION 'Lifecycle fallback requires both reviewed contact-only agent types';
    END IF;
END
$fallback$;
ALTER TABLE operations.entity_types DROP CONSTRAINT ck_entity_types_lifecycle_evidence_mode;
ALTER TABLE operations.entity_types ADD CONSTRAINT ck_entity_types_lifecycle_evidence_mode
    CHECK (lifecycle_evidence_mode IN (
        'none','direct_contact','reported_state','direct_then_reported_state',
        'direct_contact_state_fallback'));
SELECT operations.begin_change(
    'entity_type.lifecycle_policy.update',
    'PLAN-014: accept explicit agent state only without qualified direct contact.',
    '{"migration":"0357"}'::jsonb, 'migration', NULL,
    'operations.migrations', '0357', NULL, true);
UPDATE operations.entity_types SET lifecycle_evidence_mode='direct_contact_state_fallback'
 WHERE name IN ('agent.remote_access','agent.monitoring');
SELECT set_config('operations.change_action_id', '', true);
"""

REVERSE_SQL = """
SELECT operations.begin_change(
    'entity_type.lifecycle_policy.update', 'PLAN-014: restore contact-only agent policy.',
    '{"migration":"0357","reverse":true}'::jsonb, 'migration', NULL,
    'operations.migrations', '0357', NULL, true);
UPDATE operations.entity_types SET lifecycle_evidence_mode='direct_contact'
 WHERE name IN ('agent.remote_access','agent.monitoring')
   AND lifecycle_evidence_mode='direct_contact_state_fallback';
SELECT set_config('operations.change_action_id', '', true);
ALTER TABLE operations.entity_types DROP CONSTRAINT ck_entity_types_lifecycle_evidence_mode;
ALTER TABLE operations.entity_types ADD CONSTRAINT ck_entity_types_lifecycle_evidence_mode
    CHECK (lifecycle_evidence_mode IN (
        'none','direct_contact','reported_state','direct_then_reported_state'));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0356_requirement_episode_identity"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.AlterField(
            model_name="entitytype",
            name="lifecycle_evidence_mode",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("direct_contact", "Direct contact"),
                    ("reported_state", "Reported state"),
                    ("direct_then_reported_state", "Direct then reported state"),
                    (
                        "direct_contact_state_fallback",
                        "Direct contact with reported state fallback",
                    ),
                ],
                default="none",
                max_length=32,
            ),
        ),
    ]
