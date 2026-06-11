-- Remove placeholder org noise from the canonical org workflow.
-- These names are not real orgs and should not appear in the main queue.

UPDATE ninja_agent_compliance.clients
SET enabled = false,
    updated_at = now(),
    updated_by = 'agent_compliance'
WHERE lower(trim(client_name)) IN (
    'default site',
    'unknown',
    'various',
    '.default'
);

DELETE FROM ninja_agent_compliance.client_aliases
WHERE lower(trim(alias_value)) IN (
    'default site',
    'unknown',
    'various',
    '.default'
);

DELETE FROM ninja_agent_compliance.org_candidates
WHERE lower(trim(candidate_name)) IN (
    'default site',
    'unknown',
    'various',
    '.default'
);

DELETE FROM ninja_agent_compliance.org_alignment_current
WHERE lower(trim(org_name)) IN (
    'default site',
    'unknown',
    'various',
    '.default'
);

DELETE FROM ninja_agent_compliance.org_alignment_history
WHERE lower(trim(org_name)) IN (
    'default site',
    'unknown',
    'various',
    '.default'
);
