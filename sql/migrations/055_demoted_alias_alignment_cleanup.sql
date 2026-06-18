-- Clean stale aliases/alignment rows left behind by the v0.32.x
-- duplicate-client demotion flow.
--
-- Disabled/demoted clients are preserved for history, but their aliases
-- must not remain active matching/display inputs. The live symptom was
-- City Painting:
--   * client_id 7 was correctly linked to Ninja org 32 as City Painting
--   * demoted client_id 1300 still had active aliases
--   * org_alignment_current still had stale rows for both 7 and 1300

BEGIN;

UPDATE ninja_agent_compliance.client_aliases a
SET enabled = false,
    notes = COALESCE(NULLIF(a.notes, ''), 'Disabled because owning client is demoted'),
    updated_at = now(),
    updated_by = 'migration_055'
FROM ninja_agent_compliance.clients c
WHERE c.client_id = a.client_id
  AND c.source = 'demoted'
  AND NOT c.enabled
  AND a.enabled;

DELETE FROM ninja_agent_compliance.org_alignment_current a
USING ninja_agent_compliance.clients c
WHERE a.client_id = c.client_id
  AND c.source = 'demoted'
  AND NOT c.enabled;

DELETE FROM ninja_agent_compliance.org_alignment_current a
USING ninja_agent_compliance.clients c
WHERE a.client_id = c.client_id
  AND c.enabled
  AND a.org_name <> c.client_name;

COMMIT;
