CREATE SCHEMA IF NOT EXISTS ninja_agent_compliance;

CREATE TABLE ninja_agent_compliance.clients (
    client_id            bigserial PRIMARY KEY,
    client_name          text NOT NULL UNIQUE,
    enabled              boolean NOT NULL DEFAULT true,
    default_max_age_days integer NOT NULL DEFAULT 30,
    notes                text,
    source               text NOT NULL DEFAULT 'seed',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    updated_by           text NOT NULL DEFAULT 'system'
);

CREATE TABLE ninja_agent_compliance.platform_sources (
    source_id              bigserial PRIMARY KEY,
    source_key             text NOT NULL UNIQUE,
    platform               text NOT NULL CHECK (
        platform IN ('Ninja', 'SentinelOne', 'LogMeIn', 'ScreenConnect')
    ),
    source_name            text NOT NULL,
    client_id              bigint REFERENCES ninja_agent_compliance.clients(client_id),
    is_shared              boolean NOT NULL DEFAULT false,
    enabled                boolean NOT NULL DEFAULT false,
    base_url               text,
    token_url              text,
    username_secret_ref    text,
    password_secret_ref    text,
    api_token_secret_ref   text,
    client_id_secret_ref   text,
    client_secret_ref      text,
    ext_guid_secret_ref    text,
    secret_key_secret_ref  text,
    company_id_secret_ref  text,
    psk_secret_ref         text,
    notes                  text,
    source                 text NOT NULL DEFAULT 'seed',
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    updated_by             text NOT NULL DEFAULT 'system',
    CHECK (is_shared OR client_id IS NOT NULL)
);

CREATE TABLE ninja_agent_compliance.client_aliases (
    alias_id    bigserial PRIMARY KEY,
    client_id   bigint NOT NULL REFERENCES ninja_agent_compliance.clients(client_id),
    platform    text NOT NULL CHECK (
        platform IN ('Ninja', 'SentinelOne', 'LogMeIn', 'ScreenConnect')
    ),
    source_id   bigint REFERENCES ninja_agent_compliance.platform_sources(source_id),
    alias_type  text NOT NULL,
    alias_value text NOT NULL,
    enabled     boolean NOT NULL DEFAULT true,
    notes       text,
    source      text NOT NULL DEFAULT 'seed',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL DEFAULT 'system'
);

CREATE UNIQUE INDEX client_aliases_unique_key
ON ninja_agent_compliance.client_aliases (
    client_id, platform, COALESCE(source_id, 0), alias_type, alias_value
);

CREATE TABLE ninja_agent_compliance.platform_requirements (
    requirement_id     bigserial PRIMARY KEY,
    client_id          bigint REFERENCES ninja_agent_compliance.clients(client_id),
    device_scope       text NOT NULL CHECK (device_scope IN ('all', 'server', 'workstation')),
    required_platforms text[] NOT NULL,
    max_age_days       integer,
    enabled            boolean NOT NULL DEFAULT true,
    notes              text,
    source             text NOT NULL DEFAULT 'seed',
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    updated_by         text NOT NULL DEFAULT 'system'
);

CREATE UNIQUE INDEX platform_requirements_unique_key
ON ninja_agent_compliance.platform_requirements (
    COALESCE(client_id, 0), device_scope
);

CREATE TABLE ninja_agent_compliance.notification_routes (
    route_id       bigserial PRIMARY KEY,
    route_key      text NOT NULL UNIQUE,
    route_type     text NOT NULL CHECK (route_type IN ('webhook', 'email', 'zendesk')),
    display_name   text NOT NULL,
    target_ref     text,
    config         jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled        boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    updated_by     text NOT NULL DEFAULT 'system'
);

CREATE TABLE ninja_agent_compliance.alert_rules (
    rule_id           bigserial PRIMARY KEY,
    rule_key          text NOT NULL UNIQUE,
    finding_type      text NOT NULL,
    affected_platform text,
    client_id         bigint REFERENCES ninja_agent_compliance.clients(client_id),
    device_scope      text CHECK (device_scope IN ('all', 'server', 'workstation')),
    severity          text NOT NULL CHECK (severity IN ('info', 'medium', 'high', 'critical')),
    cooldown_hours    integer NOT NULL DEFAULT 24,
    route_id          bigint REFERENCES ninja_agent_compliance.notification_routes(route_id),
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text NOT NULL DEFAULT 'system'
);

CREATE TABLE ninja_agent_compliance.alert_suppressions (
    suppression_id    bigserial PRIMARY KEY,
    client_id         bigint REFERENCES ninja_agent_compliance.clients(client_id),
    norm_name         text,
    finding_type      text,
    affected_platform text,
    reason            text NOT NULL,
    expires_at        timestamptz,
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text NOT NULL DEFAULT 'system'
);

CREATE TABLE ninja_agent_compliance.source_runs (
    source_run_id bigserial PRIMARY KEY,
    run_id        bigint REFERENCES ninja_core.run_log(run_id),
    source_id     bigint NOT NULL REFERENCES ninja_agent_compliance.platform_sources(source_id),
    started_at    timestamptz NOT NULL,
    finished_at   timestamptz,
    status        text NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'disabled')),
    rows_observed integer NOT NULL DEFAULT 0,
    error_text    text
);

CREATE INDEX ON ninja_agent_compliance.source_runs (source_id, started_at DESC);

CREATE TABLE ninja_agent_compliance.platform_observations (
    observation_id        bigserial PRIMARY KEY,
    source_run_id         bigint NOT NULL REFERENCES ninja_agent_compliance.source_runs(source_run_id),
    observed_at           timestamptz NOT NULL,
    platform              text NOT NULL CHECK (
        platform IN ('Ninja', 'SentinelOne', 'LogMeIn', 'ScreenConnect')
    ),
    source_id             bigint NOT NULL REFERENCES ninja_agent_compliance.platform_sources(source_id),
    source_name           text NOT NULL,
    source_client_name    text,
    resolved_client_id    bigint REFERENCES ninja_agent_compliance.clients(client_id),
    resolved_client_name  text,
    platform_group_name   text,
    platform_group_id     text,
    platform_device_id    text,
    hostname              text NOT NULL,
    norm_name             text NOT NULL,
    match_name            text NOT NULL,
    device_type           text NOT NULL DEFAULT 'unknown',
    os_name               text,
    domain_name           text,
    is_online             boolean,
    last_seen_at          timestamptz,
    resolution_method     text NOT NULL DEFAULT 'alias',
    confidence            integer NOT NULL DEFAULT 100,
    raw_data              jsonb NOT NULL
);

CREATE INDEX ON ninja_agent_compliance.platform_observations (observed_at DESC);
CREATE INDEX ON ninja_agent_compliance.platform_observations (source_id, observed_at DESC);
CREATE INDEX ON ninja_agent_compliance.platform_observations (resolved_client_id, norm_name);
CREATE INDEX ON ninja_agent_compliance.platform_observations (platform, norm_name);
CREATE INDEX ON ninja_agent_compliance.platform_observations USING GIN (raw_data jsonb_path_ops);

CREATE TABLE ninja_agent_compliance.compliance_matrix_current (
    client_id                  bigint NOT NULL REFERENCES ninja_agent_compliance.clients(client_id),
    client_name                text NOT NULL,
    norm_name                  text NOT NULL,
    hostname                   text NOT NULL,
    device_type                text NOT NULL,
    os_name                    text,
    domain_name                text,
    required_platforms         text[] NOT NULL,
    observed_platforms         text[] NOT NULL,
    missing_required_platforms text[] NOT NULL,
    stale_required_platforms   text[] NOT NULL,
    unknown_required_platforms text[] NOT NULL,
    source_failed_platforms    text[] NOT NULL,
    is_compliant               boolean NOT NULL,
    is_stale                   boolean NOT NULL,
    is_unknown                 boolean NOT NULL,
    cross_client_conflict      boolean NOT NULL DEFAULT false,
    finding_signature          text NOT NULL,
    evaluated_at               timestamptz NOT NULL,
    PRIMARY KEY (client_id, norm_name)
);

CREATE INDEX ON ninja_agent_compliance.compliance_matrix_current (client_name);
CREATE INDEX ON ninja_agent_compliance.compliance_matrix_current (is_compliant);
CREATE INDEX ON ninja_agent_compliance.compliance_matrix_current USING GIN (missing_required_platforms);

CREATE TABLE ninja_agent_compliance.compliance_matrix_history (
    history_id                 bigserial PRIMARY KEY,
    run_id                     bigint REFERENCES ninja_core.run_log(run_id),
    client_id                  bigint REFERENCES ninja_agent_compliance.clients(client_id),
    client_name                text NOT NULL,
    norm_name                  text NOT NULL,
    hostname                   text NOT NULL,
    device_type                text NOT NULL,
    os_name                    text,
    domain_name                text,
    required_platforms         text[] NOT NULL,
    observed_platforms         text[] NOT NULL,
    missing_required_platforms text[] NOT NULL,
    stale_required_platforms   text[] NOT NULL,
    unknown_required_platforms text[] NOT NULL,
    source_failed_platforms    text[] NOT NULL,
    is_compliant               boolean NOT NULL,
    is_stale                   boolean NOT NULL,
    is_unknown                 boolean NOT NULL,
    cross_client_conflict      boolean NOT NULL DEFAULT false,
    finding_signature          text NOT NULL,
    evaluated_at               timestamptz NOT NULL
);

CREATE INDEX ON ninja_agent_compliance.compliance_matrix_history (evaluated_at DESC);
CREATE INDEX ON ninja_agent_compliance.compliance_matrix_history (client_name, norm_name);

CREATE TABLE ninja_agent_compliance.compliance_findings (
    finding_id        bigserial PRIMARY KEY,
    run_id            bigint REFERENCES ninja_core.run_log(run_id),
    finding_signature text NOT NULL,
    finding_type      text NOT NULL,
    affected_platform text,
    source_id         bigint REFERENCES ninja_agent_compliance.platform_sources(source_id),
    client_id         bigint REFERENCES ninja_agent_compliance.clients(client_id),
    client_name       text,
    norm_name         text,
    hostname          text,
    device_type       text,
    severity          text NOT NULL CHECK (severity IN ('info', 'medium', 'high', 'critical')),
    summary           text NOT NULL,
    details           jsonb NOT NULL,
    status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    first_seen_at     timestamptz NOT NULL,
    last_seen_at      timestamptz NOT NULL
);

CREATE INDEX ON ninja_agent_compliance.compliance_findings (run_id);
CREATE INDEX ON ninja_agent_compliance.compliance_findings (finding_signature, last_seen_at DESC);
CREATE INDEX ON ninja_agent_compliance.compliance_findings (status, severity);

CREATE TABLE ninja_agent_compliance.alert_state (
    finding_signature text PRIMARY KEY,
    finding_type      text NOT NULL,
    affected_platform text,
    severity          text NOT NULL,
    summary_hash      text NOT NULL,
    first_seen_at     timestamptz NOT NULL,
    last_seen_at      timestamptz NOT NULL,
    last_alerted_at   timestamptz,
    status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    repeat_count      integer NOT NULL DEFAULT 0,
    resolved_at       timestamptz
);

CREATE TABLE ninja_agent_compliance.alert_events (
    alert_event_id    bigserial PRIMARY KEY,
    finding_signature text NOT NULL REFERENCES ninja_agent_compliance.alert_state(finding_signature),
    finding_id        bigint REFERENCES ninja_agent_compliance.compliance_findings(finding_id),
    route_id          bigint REFERENCES ninja_agent_compliance.notification_routes(route_id),
    event_type        text NOT NULL CHECK (event_type IN ('new', 'changed', 'repeat', 'resolved')),
    attempted_at      timestamptz NOT NULL,
    status            text NOT NULL,
    response_code     integer,
    response_preview  text,
    payload           jsonb NOT NULL
);

CREATE INDEX ON ninja_agent_compliance.alert_events (attempted_at DESC);

CREATE OR REPLACE VIEW ninja_agent_compliance.v_source_health_current AS
SELECT DISTINCT ON (ps.source_id)
    ps.source_id,
    ps.source_key,
    ps.platform,
    ps.source_name,
    c.client_name,
    ps.is_shared,
    ps.enabled,
    sr.started_at,
    sr.finished_at,
    COALESCE(sr.status, 'disabled') AS status,
    COALESCE(sr.rows_observed, 0) AS rows_observed,
    sr.error_text
FROM ninja_agent_compliance.platform_sources ps
LEFT JOIN ninja_agent_compliance.clients c ON c.client_id = ps.client_id
LEFT JOIN ninja_agent_compliance.source_runs sr ON sr.source_id = ps.source_id
ORDER BY ps.source_id, sr.started_at DESC NULLS LAST;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_compliance_matrix_current AS
SELECT *
FROM ninja_agent_compliance.compliance_matrix_current;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_remediation_candidates AS
SELECT *
FROM ninja_agent_compliance.compliance_matrix_current
WHERE NOT is_compliant
  AND NOT is_unknown
ORDER BY client_name, hostname;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_cross_client_conflicts AS
SELECT *
FROM ninja_agent_compliance.compliance_matrix_current
WHERE cross_client_conflict
ORDER BY norm_name, client_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_active_findings AS
SELECT *
FROM ninja_agent_compliance.compliance_findings
WHERE status = 'active'
ORDER BY severity DESC, last_seen_at DESC;

INSERT INTO ninja_agent_compliance.notification_routes
    (route_key, route_type, display_name, target_ref, enabled, config)
VALUES
    ('default_webhook', 'webhook', 'Default webhook', 'AGENT_COMPLIANCE_ALERT_WEBHOOK_URL', true, '{}'::jsonb),
    ('default_email', 'email', 'Default email', 'AGENT_COMPLIANCE_ALERT_EMAIL_TO', false, '{}'::jsonb),
    ('default_zendesk', 'zendesk', 'Default Zendesk', 'AGENT_COMPLIANCE_ZENDESK_URL', false, '{}'::jsonb)
ON CONFLICT (route_key) DO NOTHING;

INSERT INTO ninja_agent_compliance.platform_requirements
    (client_id, device_scope, required_platforms, max_age_days, notes)
VALUES
    (NULL, 'all', ARRAY['Ninja', 'SentinelOne', 'LogMeIn'], 30, 'Default requirement for clients without an override')
ON CONFLICT DO NOTHING;

INSERT INTO ninja_agent_compliance.clients (client_name, default_max_age_days)
VALUES
    ('UTA', 7),
    ('A.M. Rose', 30),
    ('All Data Health', 30),
    ('BH Management', 30),
    ('C2P', 30),
    ('Chartwell Pharma', 30),
    ('CPS', 30),
    ('DJ Direct', 30),
    ('Freunds Fish', 30),
    ('GF Supplies', 30),
    ('GGI International', 30),
    ('Kerekes', 30),
    ('KIT', 30),
    ('MD Door', 30),
    ('Park Bookeeping', 30),
    ('Ruby Staffing', 30),
    ('SMS Supplies', 30),
    ('Spencer Myrtle / Express Builders', 30),
    ('Deco/Trimworx', 30),
    ('United Supply', 30),
    ('Platinum Care', 30),
    ('PCHC - Parent Care Health Care', 30),
    ('Nutty Naturals', 30),
    ('Lion HVAC', 30),
    ('Expressive Lighting', 30),
    ('County\CNY', 30),
    ('Abco - Omni Dental', 30)
ON CONFLICT (client_name) DO NOTHING;

INSERT INTO ninja_agent_compliance.platform_sources
    (source_key, platform, source_name, is_shared, enabled)
VALUES
    ('ninja_main', 'Ninja', 'NinjaOne', true, true),
    ('s1_main', 'SentinelOne', 'SentinelOne', true, false),
    ('lmi_main', 'LogMeIn', 'LogMeIn Central', true, false)
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO ninja_agent_compliance.client_aliases
    (client_id, platform, alias_type, alias_value)
SELECT c.client_id, 'Ninja', 'org_name', c.client_name
FROM ninja_agent_compliance.clients c
ON CONFLICT DO NOTHING;

INSERT INTO ninja_agent_compliance.client_aliases
    (client_id, platform, alias_type, alias_value)
SELECT c.client_id, 'SentinelOne', 'site_name',
       CASE
           WHEN c.client_name = 'All Data Health' THEN 'AllData'
           WHEN c.client_name = 'BH Management' THEN 'BH'
           WHEN c.client_name = 'Chartwell Pharma' THEN 'Chartwell'
           WHEN c.client_name = 'CPS' THEN 'City Painting (CPS)'
           WHEN c.client_name = 'GF Supplies' THEN 'GFS'
           WHEN c.client_name = 'GGI International' THEN 'GGI'
           WHEN c.client_name = 'Park Bookeeping' THEN 'Park Bookkeeping'
           WHEN c.client_name = 'Ruby Staffing' THEN 'Ruby'
           WHEN c.client_name = 'Spencer Myrtle / Express Builders' THEN 'Spencer Myrtle-Express Builders'
           WHEN c.client_name = 'Deco/Trimworx' THEN 'Trimworx-Deco-BGG'
           WHEN c.client_name = 'United Supply' THEN 'United'
           WHEN c.client_name = 'Platinum Care' THEN 'Platinum'
           WHEN c.client_name = 'PCHC - Parent Care Health Care' THEN 'PCHC'
           WHEN c.client_name = 'Nutty Naturals' THEN 'Nutty'
           WHEN c.client_name = 'Lion HVAC' THEN 'Lion'
           WHEN c.client_name = 'Expressive Lighting' THEN 'Expressive'
           WHEN c.client_name = 'County\CNY' THEN 'County'
           WHEN c.client_name = 'Abco - Omni Dental' THEN 'ABCO'
           ELSE c.client_name
       END
FROM ninja_agent_compliance.clients c
ON CONFLICT DO NOTHING;

INSERT INTO ninja_agent_compliance.client_aliases
    (client_id, platform, alias_type, alias_value)
SELECT c.client_id, 'LogMeIn', 'group_name', v.alias_value
FROM ninja_agent_compliance.clients c
JOIN (
    VALUES
        ('UTA', 'UTA'),
        ('A.M. Rose', 'A.M. Rose'),
        ('A.M. Rose', 'A.M. Rose Servers'),
        ('All Data Health', 'ADH Servers'),
        ('All Data Health', 'ADH VMH'),
        ('Chartwell Pharma', 'Chartwell-150 WELLS'),
        ('Chartwell Pharma', 'Chartwell-Amityville'),
        ('Chartwell Pharma', 'Chartwell-BP'),
        ('Chartwell Pharma', 'Chartwell-Brenner'),
        ('Chartwell Pharma', 'Chartwell-Caldwell'),
        ('Chartwell Pharma', 'Chartwell-Carmel'),
        ('Chartwell Pharma', 'Chartwell-Carmel-Servers'),
        ('Chartwell Pharma', 'Chartwell-Congers-Servers'),
        ('Chartwell Pharma', 'Chartwell-Hemlock'),
        ('Chartwell Pharma', 'Chartwell-Orangeburg'),
        ('DJ Direct', 'DJ Atlanta'),
        ('DJ Direct', 'DJ Direct CA'),
        ('DJ Direct', 'DJ Direct Highland'),
        ('DJ Direct', 'DJ-Utah'),
        ('Freunds Fish', 'Freunds Middletown'),
        ('Kerekes', 'Kerekes NJ'),
        ('KIT', 'KIT Philippines'),
        ('KIT', 'KIT USA NJ'),
        ('MD Door', 'MD Door Servers'),
        ('Ruby Staffing', 'ADH Ruby Infra')
) AS v(client_name, alias_value) ON v.client_name = c.client_name
ON CONFLICT DO NOTHING;

INSERT INTO ninja_agent_compliance.platform_requirements
    (client_id, device_scope, required_platforms, max_age_days, notes)
SELECT c.client_id, v.device_scope, v.required_platforms, v.max_age_days, v.notes
FROM ninja_agent_compliance.clients c
JOIN (
    VALUES
        ('UTA', 'server', ARRAY['Ninja', 'SentinelOne', 'LogMeIn'], 7, 'UTA servers do not require ScreenConnect in v1 seed'),
        ('UTA', 'workstation', ARRAY['Ninja', 'ScreenConnect', 'SentinelOne'], 7, 'UTA workstations require ScreenConnect'),
        ('A.M. Rose', 'all', ARRAY['Ninja', 'LogMeIn'], 30, 'Migrated from PowerShell OrgConfig'),
        ('C2P', 'all', ARRAY['Ninja', 'SentinelOne'], 30, 'Migrated from PowerShell OrgConfig'),
        ('Ruby Staffing', 'all', ARRAY['Ninja', 'SentinelOne'], 30, 'Migrated from PowerShell OrgConfig')
) AS v(client_name, device_scope, required_platforms, max_age_days, notes)
ON v.client_name = c.client_name
ON CONFLICT DO NOTHING;

WITH route AS (
    SELECT route_id FROM ninja_agent_compliance.notification_routes
    WHERE route_key = 'default_webhook'
)
INSERT INTO ninja_agent_compliance.alert_rules
    (rule_key, finding_type, affected_platform, severity, cooldown_hours, route_id)
SELECT *
FROM (
    VALUES
        ('missing_ninja', 'missing_required_platform', 'Ninja', 'critical', 24),
        ('missing_sentinelone', 'missing_required_platform', 'SentinelOne', 'critical', 24),
        ('missing_screenconnect', 'missing_required_platform', 'ScreenConnect', 'high', 24),
        ('missing_logmein', 'missing_required_platform', 'LogMeIn', 'high', 24),
        ('stale_required_platform', 'stale_required_platform', NULL, 'medium', 24),
        ('cross_client_conflict', 'cross_client_conflict', NULL, 'high', 24),
        ('source_failure', 'source_failure', NULL, 'high', 4)
) AS v(rule_key, finding_type, affected_platform, severity, cooldown_hours)
CROSS JOIN route
ON CONFLICT (rule_key) DO NOTHING;
