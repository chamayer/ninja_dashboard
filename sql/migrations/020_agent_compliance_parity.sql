CREATE TABLE IF NOT EXISTS ninja_agent_compliance.org_alignment_current (
    client_id            bigint PRIMARY KEY REFERENCES ninja_agent_compliance.clients(client_id),
    org_name             text NOT NULL,
    is_configured        boolean NOT NULL DEFAULT false,
    ninja_status         text NOT NULL,
    sc_status            text NOT NULL,
    s1_status            text NOT NULL,
    lmi_status           text NOT NULL,
    overall_status       text NOT NULL,
    ninja_platform_name  text,
    s1_platform_name     text,
    lmi_platform_name    text,
    merged_from          text[] NOT NULL DEFAULT ARRAY[]::text[],
    suggested_config     text,
    evaluated_at         timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS ninja_agent_compliance.org_alignment_history (
    history_id           bigserial PRIMARY KEY,
    run_id               bigint REFERENCES ninja_core.run_log(run_id),
    client_id            bigint REFERENCES ninja_agent_compliance.clients(client_id),
    org_name             text NOT NULL,
    is_configured        boolean NOT NULL DEFAULT false,
    ninja_status         text NOT NULL,
    sc_status            text NOT NULL,
    s1_status            text NOT NULL,
    lmi_status           text NOT NULL,
    overall_status       text NOT NULL,
    ninja_platform_name  text,
    s1_platform_name     text,
    lmi_platform_name    text,
    merged_from          text[] NOT NULL DEFAULT ARRAY[]::text[],
    suggested_config     text,
    evaluated_at         timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS org_alignment_history_evaluated_idx
ON ninja_agent_compliance.org_alignment_history (evaluated_at DESC);

CREATE INDEX IF NOT EXISTS org_alignment_current_status_idx
ON ninja_agent_compliance.org_alignment_current (overall_status);

ALTER TABLE ninja_agent_compliance.compliance_matrix_current
    ADD COLUMN IF NOT EXISTS org_align_status text,
    ADD COLUMN IF NOT EXISTS ninja_status text,
    ADD COLUMN IF NOT EXISTS sc_status text,
    ADD COLUMN IF NOT EXISTS s1_status text,
    ADD COLUMN IF NOT EXISTS lmi_status text,
    ADD COLUMN IF NOT EXISTS ninja_platform_name text,
    ADD COLUMN IF NOT EXISTS s1_platform_name text,
    ADD COLUMN IF NOT EXISTS lmi_platform_name text,
    ADD COLUMN IF NOT EXISTS s1_exempt boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS is_degraded boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS in_ninja boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS ninja_online boolean,
    ADD COLUMN IF NOT EXISTS ninja_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS ninja_device_id text,
    ADD COLUMN IF NOT EXISTS in_screenconnect boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS screenconnect_online boolean,
    ADD COLUMN IF NOT EXISTS screenconnect_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS screenconnect_device_id text,
    ADD COLUMN IF NOT EXISTS screenconnect_dup boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS in_sentinelone boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS sentinelone_online boolean,
    ADD COLUMN IF NOT EXISTS sentinelone_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS sentinelone_device_id text,
    ADD COLUMN IF NOT EXISTS in_logmein boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS logmein_online boolean,
    ADD COLUMN IF NOT EXISTS logmein_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS logmein_device_id text;

ALTER TABLE ninja_agent_compliance.compliance_matrix_history
    ADD COLUMN IF NOT EXISTS org_align_status text,
    ADD COLUMN IF NOT EXISTS ninja_status text,
    ADD COLUMN IF NOT EXISTS sc_status text,
    ADD COLUMN IF NOT EXISTS s1_status text,
    ADD COLUMN IF NOT EXISTS lmi_status text,
    ADD COLUMN IF NOT EXISTS ninja_platform_name text,
    ADD COLUMN IF NOT EXISTS s1_platform_name text,
    ADD COLUMN IF NOT EXISTS lmi_platform_name text,
    ADD COLUMN IF NOT EXISTS s1_exempt boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS is_degraded boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS in_ninja boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS ninja_online boolean,
    ADD COLUMN IF NOT EXISTS ninja_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS ninja_device_id text,
    ADD COLUMN IF NOT EXISTS in_screenconnect boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS screenconnect_online boolean,
    ADD COLUMN IF NOT EXISTS screenconnect_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS screenconnect_device_id text,
    ADD COLUMN IF NOT EXISTS screenconnect_dup boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS in_sentinelone boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS sentinelone_online boolean,
    ADD COLUMN IF NOT EXISTS sentinelone_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS sentinelone_device_id text,
    ADD COLUMN IF NOT EXISTS in_logmein boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS logmein_online boolean,
    ADD COLUMN IF NOT EXISTS logmein_last_seen timestamptz,
    ADD COLUMN IF NOT EXISTS logmein_device_id text;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_org_alignment_current AS
SELECT *
FROM ninja_agent_compliance.org_alignment_current
ORDER BY org_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_alignment_mismatches AS
SELECT *
FROM ninja_agent_compliance.org_alignment_current
WHERE overall_status NOT LIKE 'OK%'
ORDER BY org_name;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_compliance_matrix_current AS
SELECT *
FROM ninja_agent_compliance.compliance_matrix_current;

CREATE OR REPLACE VIEW ninja_agent_compliance.v_remediation_candidates AS
SELECT *
FROM ninja_agent_compliance.compliance_matrix_current
WHERE NOT is_compliant
  AND NOT is_unknown
ORDER BY client_name, hostname;
