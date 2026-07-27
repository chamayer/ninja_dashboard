-- =============================================================================
-- 072_intel_schema.sql
-- Establish the `intel` schema for external vulnerability + OSINT signal
-- data. Mirrors the way ninja_patches / ninja_activities isolate
-- source-specific stores from the operations authority. Operations owns
-- the matcher and composite scorer; intel owns the raw feeds.
--
-- ADR: operations/docs/decisions/0008-software-safety-intel-layer.md
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS intel;

GRANT USAGE ON SCHEMA intel TO operations_app, operations_readonly, metabase_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA intel
    GRANT SELECT ON TABLES TO operations_app, operations_readonly, metabase_ro;

-- CVE catalogue: one row per CVE identifier. Populated by the NVD
-- delta ingest; CVSS / EPSS / KEV columns are updated in place by the
-- respective feed connectors.
CREATE TABLE IF NOT EXISTS intel.cves (
    cve_id            text PRIMARY KEY,
    cvss_v3           numeric(3,1),
    cvss_v3_vector    text,
    cvss_v4           numeric(3,1),
    cvss_v4_vector    text,
    severity          text,                       -- derived: critical|high|medium|low|none
    published_at      timestamptz,
    last_modified_at  timestamptz,
    description       text,
    cwes              text[]        NOT NULL DEFAULT '{}',
    affected_cpes     jsonb         NOT NULL DEFAULT '[]',
    epss_score        numeric(5,4),               -- 0.0000 .. 1.0000
    epss_percentile   numeric(5,4),
    kev_flag          boolean       NOT NULL DEFAULT FALSE,
    kev_added_at      date,
    kev_notes         text,
    raw_nvd           jsonb,                      -- fidelity-at-ingest
    ingested_at       timestamptz   NOT NULL DEFAULT now(),
    updated_at        timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cves_kev_idx        ON intel.cves (kev_flag) WHERE kev_flag;
CREATE INDEX IF NOT EXISTS cves_severity_idx   ON intel.cves (severity);
CREATE INDEX IF NOT EXISTS cves_published_idx  ON intel.cves (published_at DESC);
CREATE INDEX IF NOT EXISTS cves_updated_idx    ON intel.cves (last_modified_at DESC);
CREATE INDEX IF NOT EXISTS cves_epss_idx       ON intel.cves (epss_score DESC NULLS LAST);

-- CPE 2.3 dictionary for matching software titles → CVEs.
CREATE TABLE IF NOT EXISTS intel.cpes (
    cpe23             text PRIMARY KEY,           -- cpe:2.3:a:vendor:product:version:...
    vendor            text NOT NULL,
    product           text NOT NULL,
    version           text,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    raw_nvd           jsonb
);

CREATE INDEX IF NOT EXISTS cpes_vendor_product_idx
    ON intel.cpes (LOWER(vendor), LOWER(product));

-- Operations-owned mapping between canonical software titles and CVEs.
-- Populated by the matcher; readable by the scorer + UI.
-- Kept in the operations schema so the intel schema remains a raw feed;
-- tenant-scoped like every other operations row.
CREATE TABLE IF NOT EXISTS operations.cve_match (
    id                bigserial PRIMARY KEY,
    tenant_id         bigint NOT NULL,
    canonical_name    text   NOT NULL,
    cve_id            text   NOT NULL REFERENCES intel.cves(cve_id) ON DELETE CASCADE,
    match_kind        text   NOT NULL,          -- cpe_exact | cpe_wildcard | publisher_fuzzy
    version_range     text,
    confidence        text   NOT NULL DEFAULT 'high',  -- high | medium | low
    matched_at        timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS cve_match_scope_idx
    ON operations.cve_match (tenant_id, canonical_name, cve_id, match_kind);
CREATE INDEX IF NOT EXISTS cve_match_canonical_idx
    ON operations.cve_match (tenant_id, LOWER(canonical_name));
CREATE INDEX IF NOT EXISTS cve_match_cve_idx
    ON operations.cve_match (cve_id);

-- OSINT / community signals attached to a canonical software title or a
-- publisher name. Sources: winget, chocolatey, otx, malwarebazaar,
-- threatfox, virustotal, metadefender, circl_hashlookup. Signal_type
-- shape lets a source contribute either a category tag or a threat hit
-- without a schema change per source.
CREATE TABLE IF NOT EXISTS operations.safety_signal (
    id                bigserial PRIMARY KEY,
    tenant_id         bigint NOT NULL,
    canonical_name    text   NOT NULL DEFAULT '',
    publisher         text   NOT NULL DEFAULT '',
    source            text   NOT NULL,          -- winget|chocolatey|otx|malwarebazaar|...
    signal_type       text   NOT NULL,          -- category|threat_hit|publisher_bad|community_flag
    severity          text   NOT NULL DEFAULT 'info', -- info|low|medium|high|critical
    details           jsonb  NOT NULL DEFAULT '{}',
    observed_at       timestamptz NOT NULL DEFAULT now(),
    -- Exactly one of canonical_name / publisher must be non-empty (like
    -- SoftwareDecision). Enforced below.
    CONSTRAINT ck_safety_signal_scope_key_xor CHECK (
        (canonical_name <> '' AND publisher = '')
        OR (canonical_name = '' AND publisher <> '')
        OR (canonical_name <> '' AND publisher <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS safety_signal_scope_idx
    ON operations.safety_signal (
        tenant_id, LOWER(canonical_name), LOWER(publisher), source, signal_type
    );
CREATE INDEX IF NOT EXISTS safety_signal_canonical_idx
    ON operations.safety_signal (tenant_id, LOWER(canonical_name))
    WHERE canonical_name <> '';
CREATE INDEX IF NOT EXISTS safety_signal_publisher_idx
    ON operations.safety_signal (tenant_id, LOWER(publisher))
    WHERE publisher <> '';

-- On-demand lookup cache. Populated when an operator clicks the
-- "Look up on VirusTotal / MetaDefender / abuse.ch" button on a title
-- detail page. Rows > TTL (48 h default) are stale; the click refetches.
CREATE TABLE IF NOT EXISTS operations.title_intel_cache (
    id                bigserial PRIMARY KEY,
    tenant_id         bigint NOT NULL,
    canonical_name    text   NOT NULL,
    source            text   NOT NULL,          -- virustotal|metadefender|abusech_mb|abusech_tf|circl_hashlookup
    looked_up_at      timestamptz NOT NULL DEFAULT now(),
    looked_up_by_id   integer,                  -- FK to django auth_user, kept nullable so system refresh works
    result            jsonb  NOT NULL DEFAULT '{}',
    result_summary    text
);

CREATE INDEX IF NOT EXISTS title_intel_cache_canonical_idx
    ON operations.title_intel_cache (tenant_id, LOWER(canonical_name), source, looked_up_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON operations.title_intel_cache TO operations_app;
GRANT USAGE, SELECT ON SEQUENCE operations.title_intel_cache_id_seq TO operations_app;
GRANT SELECT ON operations.title_intel_cache TO operations_readonly, metabase_ro;

-- Ingest run status per intel connector, so "nothing hidden" —
-- operators can see when a feed last succeeded, last failed, and what
-- happened last time.
CREATE TABLE IF NOT EXISTS operations.intel_ingest_status (
    connector         text PRIMARY KEY,         -- nvd|cisa_kev|epss|winget|chocolatey|otx|abusech_mb|abusech_tf
    last_run_at       timestamptz,
    last_success_at   timestamptz,
    last_status       text,                     -- ok|degraded|failed|skipped
    last_error        text,
    rows_touched      bigint,
    notes             text
);

-- Ensure future tables land under the same grants without further
-- boilerplate in follow-up migrations.
ALTER DEFAULT PRIVILEGES IN SCHEMA operations
    GRANT SELECT ON TABLES TO operations_app, operations_readonly, metabase_ro;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    intel.cves,
    intel.cpes,
    operations.cve_match,
    operations.safety_signal,
    operations.intel_ingest_status
TO operations_app;

GRANT SELECT ON
    intel.cves,
    intel.cpes,
    operations.cve_match,
    operations.safety_signal,
    operations.intel_ingest_status
TO operations_readonly, metabase_ro;

GRANT USAGE, SELECT ON SEQUENCE operations.cve_match_id_seq TO operations_app;
GRANT USAGE, SELECT ON SEQUENCE operations.safety_signal_id_seq TO operations_app;
