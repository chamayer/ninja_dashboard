from django.db import migrations


SQL = """
ALTER TABLE operations.identity_candidates
    ADD COLUMN IF NOT EXISTS current_observation_id UUID;

DO $$
BEGIN
    IF to_regclass('operations.entity_observation_current') IS NOT NULL THEN
        ALTER TABLE operations.identity_candidates
            DROP CONSTRAINT IF EXISTS identity_candidates_current_observation_fk;
        ALTER TABLE operations.identity_candidates
            ADD CONSTRAINT identity_candidates_current_observation_fk
            FOREIGN KEY (current_observation_id)
            REFERENCES operations.entity_observation_current(observation_id)
            ON DELETE SET NULL;
    END IF;
END $$;

UPDATE operations.identity_candidates ic
   SET current_observation_id = c.observation_id
  FROM operations.entity_observation_current c
 WHERE ic.current_observation_id IS NULL
   AND ic.observation_id = c.observation_id;

CREATE INDEX IF NOT EXISTS idx_identity_candidates_current_observation
    ON operations.identity_candidates (current_observation_id);
"""


class Migration(migrations.Migration):
    dependencies = [("operations", "0069_update_observation_queue_target")]
    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
