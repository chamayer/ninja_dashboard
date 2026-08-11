-- 087: automated Windows servicing lifecycle state.
--
-- Ninja already retains Windows buildNumber/releaseId and endoflife.date
-- already supplies build-bearing Windows release cycles.  This migration
-- joins those two evidence streams without an operator-maintained build map.
-- Generic product/edition rules are immutable reference data; builds and
-- lifecycle dates continue to refresh from the upstream corpus.

ALTER TABLE intel.eol_releases
    ADD COLUMN IF NOT EXISTS eoas_from date,
    ADD COLUMN IF NOT EXISTS is_eoas boolean,
    ADD COLUMN IF NOT EXISTS eoes_from date,
    ADD COLUMN IF NOT EXISTS is_eoes boolean;

COMMENT ON COLUMN intel.eol_releases.eoas_from IS
    'End of active support from endoflife.date API v1 (eoasFrom).';
COMMENT ON COLUMN intel.eol_releases.eoes_from IS
    'End of extended security support from endoflife.date API v1 (eoesFrom).';

CREATE TABLE IF NOT EXISTS intel.windows_servicing_rules (
    rule_key         text PRIMARY KEY,
    rule_kind        text NOT NULL CHECK (rule_kind IN ('product', 'edition')),
    priority         integer NOT NULL,
    product_name     text NOT NULL,
    os_name_pattern  text NOT NULL,
    cycle_pattern    text,
    notes            text NOT NULL DEFAULT '',
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_windows_servicing_rule_shape CHECK (
        (rule_kind = 'product' AND cycle_pattern IS NULL)
        OR (rule_kind = 'edition' AND cycle_pattern IS NOT NULL)
    )
);

INSERT INTO intel.windows_servicing_rules
    (rule_key, rule_kind, priority, product_name, os_name_pattern,
     cycle_pattern, notes)
VALUES
    ('product.windows-server', 'product', 10, 'windows-server',
     '(?i)\b(?:windows|hyper-v)\s+server\b', NULL,
     'Server product selection; build candidates come from the corpus.'),
    ('product.windows-client', 'product', 20, 'windows',
     '(?i)\bwindows\b', NULL,
     'Client product fallback after the server rule.'),
    ('edition.iot-lts', 'edition', 10, 'windows',
     '(?i)\b(?:windows\s+)?iot\b', '-iot-lts$',
     'Select the IoT long-term servicing cycle when a build is shared.'),
    ('edition.lts', 'edition', 20, 'windows',
     '(?i)\b(?:ltsc|ltsb)\b', '(?<!-iot)-lts$',
     'Select the Enterprise long-term servicing cycle when shared.'),
    ('edition.enterprise', 'edition', 30, 'windows',
     '(?i)\b(?:enterprise|education)\b', '-e$',
     'Select Enterprise/Education servicing when a build is shared.'),
    ('edition.workstation', 'edition', 40, 'windows',
     '(?i)\b(?:home|pro(?:fessional)?|workstation)\b', '-w$',
     'Select Home/Pro/Workstation servicing when a build is shared.')
ON CONFLICT (rule_key) DO UPDATE SET
    rule_kind       = EXCLUDED.rule_kind,
    priority        = EXCLUDED.priority,
    product_name    = EXCLUDED.product_name,
    os_name_pattern = EXCLUDED.os_name_pattern,
    cycle_pattern   = EXCLUDED.cycle_pattern,
    notes           = EXCLUDED.notes,
    updated_at      = now();

CREATE INDEX IF NOT EXISTS windows_servicing_rules_order_idx
    ON intel.windows_servicing_rules (rule_kind, priority, rule_key);

CREATE TABLE IF NOT EXISTS operations.device_windows_servicing_current (
    tenant_id                    bigint NOT NULL,
    device_id                    uuid NOT NULL,
    client_id                    uuid,
    os_name                      text NOT NULL DEFAULT '',
    os_build_number              text NOT NULL DEFAULT '',
    os_release_id                text NOT NULL DEFAULT '',
    build_number                 integer,
    product_name                 text,
    cycle                        text,
    release_label                text NOT NULL DEFAULT '',
    support_state                text NOT NULL,
    active_support_ends_on       date,
    security_support_ends_on     date,
    extended_security_ends_on    date,
    is_lts                       boolean NOT NULL DEFAULT false,
    extended_security_available boolean NOT NULL DEFAULT false,
    classification_reason       text NOT NULL DEFAULT '',
    evidence_source              text NOT NULL DEFAULT '',
    evaluated_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id),
    CONSTRAINT fk_windows_servicing_device
        FOREIGN KEY (tenant_id, device_id)
        REFERENCES operations.devices (tenant_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_windows_servicing_release
        FOREIGN KEY (product_name, cycle)
        REFERENCES intel.eol_releases (product_name, cycle),
    CONSTRAINT ck_windows_servicing_state CHECK (support_state IN (
        'supported', 'security_support', 'approaching_eol',
        'eol_esu_available', 'eol', 'unknown'
    ))
);

CREATE INDEX IF NOT EXISTS device_windows_servicing_state_idx
    ON operations.device_windows_servicing_current
       (tenant_id, support_state, security_support_ends_on);
CREATE INDEX IF NOT EXISTS device_windows_servicing_client_idx
    ON operations.device_windows_servicing_current
       (tenant_id, client_id, support_state);

ALTER TABLE operations.device_windows_servicing_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.device_windows_servicing_current FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation
    ON operations.device_windows_servicing_current
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', true)::bigint);

REVOKE ALL ON intel.windows_servicing_rules,
    operations.device_windows_servicing_current FROM PUBLIC;
GRANT SELECT ON intel.windows_servicing_rules
    TO ninja_ingest, operations_app, operations_readonly, metabase_ro;
GRANT SELECT ON operations.device_windows_servicing_current
    TO operations_app, operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON operations.device_windows_servicing_current TO ninja_ingest;

COMMENT ON TABLE intel.windows_servicing_rules IS
    'Version-controlled generic Windows product/edition rules. Builds and '
    'dates are never maintained here; they derive from intel.eol_releases.';
COMMENT ON TABLE operations.device_windows_servicing_current IS
    'Projector-owned current Windows servicing state derived from source OS '
    'evidence and the automatically refreshed endoflife.date corpus.';
