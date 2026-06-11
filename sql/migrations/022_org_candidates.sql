CREATE TABLE IF NOT EXISTS ninja_agent_compliance.org_candidates (
    candidate_id      bigserial PRIMARY KEY,
    norm_name         text NOT NULL,
    candidate_name    text NOT NULL,
    platform          text NOT NULL CHECK (platform IN ('Ninja', 'SentinelOne', 'LogMeIn', 'ScreenConnect')),
    source_name       text,
    observed_count    integer NOT NULL DEFAULT 0,
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    suggested_target  text,
    status            text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'ignored', 'promoted')),
    notes             text,
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text NOT NULL DEFAULT 'system',
    UNIQUE (norm_name, platform, candidate_name)
);

CREATE INDEX IF NOT EXISTS org_candidates_enabled_idx
    ON ninja_agent_compliance.org_candidates (enabled)
    WHERE enabled;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_org_candidates_current AS
SELECT *
FROM ninja_agent_compliance.org_candidates
WHERE enabled
ORDER BY last_seen_at DESC, candidate_name;
