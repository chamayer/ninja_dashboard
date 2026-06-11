-- Clean up legacy/bad seed clients that are platform aliases or review-only
-- names, not authoritative managed orgs.
--
-- PowerShell parity:
--   ADH Servers, ADH VMH, DJ Atlanta, Freunds Middletown, Park Bookkeeping,
--   and Spencer Myrtle-Express Builders are aliases in $OrgConfig, not
--   standalone orgs.
--
-- Operational cleanup:
--   The remaining names below were previously promoted into clients as seed
--   rows but are not in the repo seed list or PowerShell $OrgConfig. Keep them
--   out of the authoritative org list so a future ingest can surface them as
--   review candidates.

WITH alias_map(target_client_name, platform, alias_type, alias_value) AS (
    VALUES
        ('All Data Health', 'LogMeIn', 'group_name', 'ADH Servers'),
        ('All Data Health', 'LogMeIn', 'group_name', 'ADH VMH'),
        ('DJ Direct', 'LogMeIn', 'group_name', 'DJ Atlanta'),
        ('Freunds Fish', 'LogMeIn', 'group_name', 'Freunds Middletown'),
        ('Park Bookeeping', 'SentinelOne', 'site_name', 'Park Bookkeeping'),
        ('Park Bookeeping', 'LogMeIn', 'group_name', 'Park Bookkeeping'),
        ('Spencer Myrtle / Express Builders', 'SentinelOne', 'site_name', 'Spencer Myrtle-Express Builders')
)
INSERT INTO ninja_agent_compliance.client_aliases
    (client_id, platform, alias_type, alias_value, source, notes, updated_by)
SELECT c.client_id,
       m.platform,
       m.alias_type,
       m.alias_value,
       'seed',
       'Alias-only seed cleanup; migrated from PowerShell-style org mapping',
       'migration_029'
FROM alias_map m
JOIN ninja_agent_compliance.clients c
  ON c.client_name = m.target_client_name
ON CONFLICT (client_id, platform, (COALESCE(source_id, 0)), alias_type, alias_value)
DO UPDATE SET
    enabled = true,
    source = 'seed',
    notes = EXCLUDED.notes,
    updated_at = now(),
    updated_by = EXCLUDED.updated_by;

WITH demoted(client_name) AS (
    VALUES
        ('ADH Servers'),
        ('ADH VMH'),
        ('Bobov45'),
        ('D Miller Books'),
        ('DJ Atlanta'),
        ('Freunds Middletown'),
        ('Glas'),
        ('Park Bookkeeping'),
        ('Ready'),
        ('Silk Edge'),
        ('Silvercup'),
        ('Spencer Myrtle-Express Builders'),
        ('TSK')
),
demoted_ids AS (
    SELECT c.client_id
    FROM ninja_agent_compliance.clients c
    JOIN demoted d ON d.client_name = c.client_name
)
UPDATE ninja_agent_compliance.client_aliases a
SET enabled = false,
    notes = COALESCE(NULLIF(a.notes, ''), 'Disabled because parent client was demoted from authoritative seed'),
    updated_at = now(),
    updated_by = 'migration_029'
FROM demoted_ids d
WHERE a.client_id = d.client_id;

WITH demoted(client_name) AS (
    VALUES
        ('ADH Servers'),
        ('ADH VMH'),
        ('Bobov45'),
        ('D Miller Books'),
        ('DJ Atlanta'),
        ('Freunds Middletown'),
        ('Glas'),
        ('Park Bookkeeping'),
        ('Ready'),
        ('Silk Edge'),
        ('Silvercup'),
        ('Spencer Myrtle-Express Builders'),
        ('TSK')
),
demoted_ids AS (
    SELECT c.client_id
    FROM ninja_agent_compliance.clients c
    JOIN demoted d ON d.client_name = c.client_name
)
UPDATE ninja_agent_compliance.platform_requirements r
SET enabled = false,
    notes = COALESCE(NULLIF(r.notes, ''), 'Disabled because parent client was demoted from authoritative seed'),
    updated_at = now(),
    updated_by = 'migration_029'
FROM demoted_ids d
WHERE r.client_id = d.client_id;

WITH demoted(client_name) AS (
    VALUES
        ('ADH Servers'),
        ('ADH VMH'),
        ('Bobov45'),
        ('D Miller Books'),
        ('DJ Atlanta'),
        ('Freunds Middletown'),
        ('Glas'),
        ('Park Bookkeeping'),
        ('Ready'),
        ('Silk Edge'),
        ('Silvercup'),
        ('Spencer Myrtle-Express Builders'),
        ('TSK')
),
demoted_ids AS (
    SELECT c.client_id
    FROM ninja_agent_compliance.clients c
    JOIN demoted d ON d.client_name = c.client_name
)
UPDATE ninja_agent_compliance.platform_sources ps
SET enabled = false,
    notes = COALESCE(NULLIF(ps.notes, ''), 'Disabled because parent client was demoted from authoritative seed'),
    updated_at = now(),
    updated_by = 'migration_029'
FROM demoted_ids d
WHERE ps.client_id = d.client_id;

WITH demoted(client_name) AS (
    VALUES
        ('ADH Servers'),
        ('ADH VMH'),
        ('Bobov45'),
        ('D Miller Books'),
        ('DJ Atlanta'),
        ('Freunds Middletown'),
        ('Glas'),
        ('Park Bookkeeping'),
        ('Ready'),
        ('Silk Edge'),
        ('Silvercup'),
        ('Spencer Myrtle-Express Builders'),
        ('TSK')
)
UPDATE ninja_agent_compliance.clients c
SET enabled = false,
    source = 'demoted',
    notes = COALESCE(NULLIF(c.notes, ''), 'Demoted from authoritative seed; preserved for history'),
    updated_at = now(),
    updated_by = 'migration_029'
FROM demoted d
WHERE c.client_name = d.client_name;

DELETE FROM ninja_agent_compliance.org_alignment_current a
USING ninja_agent_compliance.clients c
WHERE a.client_id = c.client_id
  AND c.source = 'demoted'
  AND NOT c.enabled;

UPDATE ninja_agent_compliance.org_candidates oc
SET status = 'open',
    enabled = true,
    updated_at = now(),
    updated_by = 'migration_029'
WHERE lower(trim(candidate_name)) IN (
    'bobov45',
    'd miller books',
    'glas',
    'ready',
    'silk edge',
    'silvercup',
    'tsk'
);
