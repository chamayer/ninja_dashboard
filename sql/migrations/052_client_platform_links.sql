-- Stable id-to-id mapping between our clients and upstream platform
-- orgs / groups / sites. Replaces name-matching as the primary
-- customer identity mechanism. A rename in any platform (same
-- platform_group_id, new platform_group_name) leaves the link
-- untouched and updates only the display name on `clients`.
--
-- One row per (platform, platform_group_id, source_id). source_id is
-- nullable because most platforms (Ninja, S1, LMI) have one shared
-- API source; ScreenConnect has one source per client and benefits
-- from the explicit qualifier.

CREATE TABLE IF NOT EXISTS ninja_agent_compliance.client_platform_links (
    link_id           bigserial PRIMARY KEY,
    client_id         bigint NOT NULL REFERENCES ninja_agent_compliance.clients(client_id) ON DELETE CASCADE,
    platform          text   NOT NULL CHECK (
        platform IN ('Ninja','SentinelOne','LogMeIn','ScreenConnect')
    ),
    platform_group_id text   NOT NULL,
    source_id         bigint REFERENCES ninja_agent_compliance.platform_sources(source_id),
    first_seen_name   text,
    last_seen_name    text,
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    notes             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text NOT NULL DEFAULT 'system'
);

CREATE UNIQUE INDEX IF NOT EXISTS client_platform_links_unique_key
    ON ninja_agent_compliance.client_platform_links (
        platform, platform_group_id, COALESCE(source_id, 0)
    );

CREATE INDEX IF NOT EXISTS client_platform_links_client_idx
    ON ninja_agent_compliance.client_platform_links (client_id);

CREATE INDEX IF NOT EXISTS client_platform_links_platform_idx
    ON ninja_agent_compliance.client_platform_links (platform, platform_group_id);
