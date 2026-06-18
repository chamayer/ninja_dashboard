-- Make every code-known placeholder customer name operator-visible.
--
-- Policy: no customer/org name should disappear solely because code
-- classified it as noise. The only active ignore bucket for customer
-- names is org_excludes, which is visible in Metabase's "Ignored
-- customer names" table and can be restored by operators when source
-- is manual. These seed rows mirror normalize.py's placeholder set.

BEGIN;

INSERT INTO ninja_agent_compliance.org_excludes
    (pattern, source, notes, enabled, updated_by)
VALUES
    ('default site', 'seed',
     'System-visible placeholder bucket; mirrors code placeholder defaultsite',
     true, 'migration_056'),
    ('default', 'seed',
     'System-visible placeholder bucket; mirrors code placeholder default',
     true, 'migration_056'),
    ('unknown', 'seed',
     'System-visible placeholder bucket; observed as platform noise unless reviewed',
     true, 'migration_056'),
    ('various', 'seed',
     'System-visible placeholder bucket; observed as platform noise unless reviewed',
     true, 'migration_056')
ON CONFLICT (pattern) DO UPDATE SET
    enabled = true,
    source = CASE
        WHEN ninja_agent_compliance.org_excludes.source = 'manual' THEN 'manual'
        ELSE EXCLUDED.source
    END,
    notes = COALESCE(NULLIF(ninja_agent_compliance.org_excludes.notes, ''), EXCLUDED.notes),
    updated_at = now(),
    updated_by = EXCLUDED.updated_by;

UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'ignored',
    enabled = false,
    updated_at = now(),
    updated_by = 'migration_056'
WHERE lower(trim(candidate_name)) IN ('default site', 'default', 'unknown', 'various')
  AND enabled;

COMMIT;
