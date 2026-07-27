from __future__ import annotations

from typing import ClassVar

from django.db import migrations

SQL = """
DO $$
BEGIN
    -- Migration 0054 intentionally retired this side table. Keep this
    -- compatibility migration safe for databases where that retirement has
    -- already occurred, while preserving the intended linkage for older or
    -- partially rolled-back installations where the table still exists.
    IF to_regclass('operations.identity_candidates') IS NOT NULL THEN
        ALTER TABLE operations.identity_candidates
            ADD COLUMN IF NOT EXISTS current_observation_id UUID;

        IF to_regclass('operations.entity_observation_current') IS NOT NULL THEN
            ALTER TABLE operations.identity_candidates
                DROP CONSTRAINT IF EXISTS identity_candidates_current_observation_fk;
            ALTER TABLE operations.identity_candidates
                ADD CONSTRAINT identity_candidates_current_observation_fk
                FOREIGN KEY (current_observation_id)
                REFERENCES operations.entity_observation_current(observation_id)
                ON DELETE SET NULL;

            UPDATE operations.identity_candidates ic
               SET current_observation_id = c.observation_id
              FROM operations.entity_observation_current c
             WHERE ic.current_observation_id IS NULL
               AND ic.observation_id = c.observation_id;
        END IF;

        CREATE INDEX IF NOT EXISTS idx_identity_candidates_current_observation
            ON operations.identity_candidates (current_observation_id);
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("operations", "0069_update_observation_queue_target")]
    operations: ClassVar = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
