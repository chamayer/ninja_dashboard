-- Replaces the hardcoded ORG_EXCLUDES = {"abe private", "amrose-test"} constant
-- in ingest/agent_compliance/config_loader.py with a DB-backed list the
-- operator can edit without redeploying.
--
-- PowerShell parity: this table is the direct equivalent of $MultiOrgExclude
-- in Multi_org_agent_compliance.ps1 (line 183). PS shipped with exactly the
-- same two seed values; nothing else was excluded by default. The PS author
-- separately documented $LMIGroupExclude with COMMENTED-OUT examples of
-- "Unknown" and ".Default" — meaning they recognised those as common noise
-- but deliberately left the decision to the operator. We mirror that stance:
-- seed only the two PS values, let the operator add more from the dashboard.

CREATE TABLE IF NOT EXISTS ninja_agent_compliance.org_excludes (
    pattern      text PRIMARY KEY,
    source       text NOT NULL DEFAULT 'manual'
                 CHECK (source IN ('manual', 'seed')),
    notes        text,
    enabled      boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   text
);

-- Patterns are stored normalized: lowercased + trimmed. Match against
-- LOWER(TRIM(platform_group_name)) at ingest time and in dashboard SQL.

CREATE INDEX IF NOT EXISTS org_excludes_enabled_idx
    ON ninja_agent_compliance.org_excludes (enabled)
    WHERE enabled;

INSERT INTO ninja_agent_compliance.org_excludes (pattern, source, notes)
VALUES
    ('abe private', 'seed',
     'Internal non-managed devices (PowerShell $MultiOrgExclude parity)'),
    ('amrose-test', 'seed',
     'Internal test environment (PowerShell $MultiOrgExclude parity)')
ON CONFLICT (pattern) DO NOTHING;
