-- 104: general software categorization -- evidence, authority, one effective
-- relation. Mirrors 093's capability contract exactly, on a different axis.
--
-- Recognizes DESCRIPTIVE categories (browser, media, developer tools, cloud
-- storage, ...) from Winget/Chocolatey package tags. Explicitly NOT the three
-- security-relevant capabilities (endpoint_security, rmm, remote_access) --
-- those remain owned by catalog.capability and are never re-derived here.
-- Measured 2026-08-19: anydesk, teamviewer and chrome-remote-desktop already
-- carry real tags ("remote-control", "rdp", "remote") that would otherwise
-- assert a second, competing "remote access" truth outside catalog.capability
-- for products it already covers. category_tag_rule is seeded with none of
-- that vocabulary mapped anywhere, by omission, not oversight -- see the seed
-- block below.
--
-- Same three questions as capability (ADR-0018), restated for taxonomy:
--   category truth   -- what kind of software IS this   (here, global)
--   ...policy sanctioning and trust do not apply to a descriptive category;
--   there is no "unauthorized_browser" finding and never will be. This
--   table drives display and filtering only. It has no may_alert axis at
--   all -- unlike capability_source, category_source needs none, because
--   nothing here can ever raise a finding.
--
-- Coverage measured before designing anything: Winget's real (post-fix,
-- exact-match) hit rate is 16 matches per 500 titles searched, 3.2%.
-- Projected across the full 22,119-title fleet at the current crawl rate:
-- roughly a few hundred to low thousands of titles, not "most software".
-- This schema is sized for that reality -- small registry, curated seed,
-- evidence-backed only -- not for an imagined broad taxonomy.
--
-- Global, no tenant, no RLS: category is a property of the product, like
-- capability and like catalog.software_versions.eol_date.

-- Vocabulary as data (ADR-0012 section 6): a new category is an INSERT.
-- Deliberately excludes browser/media/... naming collisions with
-- catalog.capability's three keys -- there are none today, and this table's
-- own rows must never be named endpoint_security/rmm/remote_access, which
-- the check below enforces rather than trusts.
CREATE TABLE IF NOT EXISTS catalog.software_category (
    key         text PRIMARY KEY,
    label       text NOT NULL,
    description text NOT NULL DEFAULT '',
    CONSTRAINT ck_software_category_not_a_capability CHECK (
        key NOT IN ('endpoint_security', 'rmm', 'remote_access')
    )
);

INSERT INTO catalog.software_category (key, label, description) VALUES
    ('browser', 'Web browser',
     'Web browsers and browser engines.'),
    ('dev_tools', 'Developer tools',
     'Version control, language runtimes, CLIs, SDKs, package managers.'),
    ('media', 'Media playback and editing',
     'Audio/video/image players, downloaders and editors.'),
    ('cloud_storage', 'Cloud storage and sync',
     'File sync and cloud storage clients.'),
    ('archive_utility', 'Archive and compression',
     'Archive, compression and extraction tools.'),
    ('system_update', 'System and vendor update tooling',
     'OS and vendor update/installation assistants -- not the OS itself.'),
    ('virtualization', 'Virtualization',
     'Hypervisor tooling and guest utilities.'),
    ('graphics_design', 'Graphics and design',
     'Vector/raster graphics and design tooling.'),
    ('communication', 'Messaging and conferencing',
     'Chat, messaging and conferencing tools that are not remote-control '
     || 'software -- see the exclusion note above for why remote-control '
     || 'tools stay out of this table entirely.'),
    ('utility', 'General utility',
     'Single-purpose desktop utilities not otherwise categorized.')
ON CONFLICT (key) DO NOTHING;

-- Two sources today; a third (operator manual tagging) needs no registry row,
-- same reasoning as capability_source's own comment: an operator table
-- carries its own authority and does not need to declare itself here.
CREATE TABLE IF NOT EXISTS catalog.category_source (
    source_key text PRIMARY KEY,
    managed_by text NOT NULL,
    enabled    boolean NOT NULL DEFAULT TRUE,
    notes      text NOT NULL DEFAULT ''
);

INSERT INTO catalog.category_source (source_key, managed_by, notes) VALUES
    ('winget_tag',     'migration', 'Winget package tags, exact-match enricher.'),
    ('chocolatey_tag', 'migration', 'Chocolatey package tags, exact-match enricher.')
ON CONFLICT (source_key) DO NOTHING;

-- Tag -> category, data-driven (ADR-0012 section 6again): never a Python
-- dict. Curated, not automatic -- a raw tag pass would turn "admin" (13
-- occurrences in the real sample, Chocolatey's own install-metadata
-- convention, not a category) into a meaningless bucket. Seeded below from
-- actual observed tags only; an unmapped tag stays unmapped rather than
-- guessed.
CREATE TABLE IF NOT EXISTS catalog.category_tag_rule (
    id       bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    tag      text NOT NULL,
    category text NOT NULL REFERENCES catalog.software_category (key),
    enabled  boolean NOT NULL DEFAULT TRUE,
    notes    text NOT NULL DEFAULT '',
    CONSTRAINT ck_category_tag_rule_tag_lower CHECK (tag = LOWER(tag)),
    UNIQUE (tag, category)
);

CREATE INDEX IF NOT EXISTS idx_category_tag_rule_tag
    ON catalog.category_tag_rule (tag) WHERE enabled;

-- Seeded from the real tag vocabulary measured 2026-08-19 across 47 exact
-- matches (16 Winget, 31 Chocolatey). One tag maps to at most one category;
-- ambiguous or capability-adjacent tags (remote, remote-control, rdp,
-- remote-desktop, control, vpn, admin, freeware, cross-platform, foss,
-- utility-as-a-bare-word) are deliberately NOT mapped -- see notes per row
-- where the omission needs explaining.
INSERT INTO catalog.category_tag_rule (tag, category, notes) VALUES
    ('browser', 'browser', ''),
    ('web-browser', 'browser', ''),
    ('chromium', 'browser', ''),
    ('webpage', 'browser', ''),
    ('cli', 'dev_tools', ''),
    ('command-line', 'dev_tools', ''),
    ('commandline', 'dev_tools', ''),
    ('dvcs', 'dev_tools', ''),
    ('vcs', 'dev_tools', ''),
    ('version-control', 'dev_tools', ''),
    ('git', 'dev_tools', ''),
    ('javascript', 'dev_tools', ''),
    ('nodejs', 'dev_tools', ''),
    ('npm', 'dev_tools', ''),
    ('programming', 'dev_tools', ''),
    ('coding', 'dev_tools', ''),
    ('development', 'dev_tools', ''),
    ('sdk', 'dev_tools', ''),
    ('api', 'dev_tools', ''),
    ('video', 'media', ''),
    ('video-player', 'media', ''),
    ('media-player', 'media', ''),
    ('multimedia', 'media', ''),
    ('audio', 'media', ''),
    ('dvd', 'media', ''),
    ('downloader', 'media',
     'Measured on "4k video downloader": a media-specific downloader, not '
     || 'general file transfer.'),
    ('music', 'media', ''),
    ('cloud', 'cloud_storage',
     'Measured only on dropbox/onedrive so far, both storage products. Not '
     || 'mapped to cloud_storage if a future exact match is a cloud compute '
     || 'or cloud security product instead -- revisit if that occurs.'),
    ('sync', 'cloud_storage', ''),
    ('storage', 'cloud_storage', ''),
    ('backup', 'cloud_storage',
     'Measured on onedrive, whose backup feature is storage sync. Revisit '
     || 'if a dedicated backup product (not sync-based) is ever matched.'),
    ('7zip', 'archive_utility', ''),
    ('compress', 'archive_utility', ''),
    ('extract', 'archive_utility', ''),
    ('unrar', 'archive_utility', ''),
    ('unzip', 'archive_utility', ''),
    ('archive', 'archive_utility', ''),
    ('zip', 'archive_utility', ''),
    ('assistant', 'system_update',
     'Measured on Windows 10/11 update and installation assistants only.'),
    ('installation-assistant', 'system_update', ''),
    ('vmware', 'virtualization', ''),
    ('esxi', 'virtualization', ''),
    ('vsphere', 'virtualization', ''),
    ('drawing', 'graphics_design', ''),
    ('vector-graphics', 'graphics_design', ''),
    ('svg', 'graphics_design', ''),
    ('icons', 'graphics_design', ''),
    ('art', 'graphics_design', ''),
    ('conference', 'communication', ''),
    ('conferencing', 'communication', ''),
    ('meeting', 'communication', ''),
    ('imessage', 'communication', ''),
    ('clipboard', 'utility', ''),
    ('multi-monitor', 'utility', '')
ON CONFLICT (tag, category) DO NOTHING;

-- Machine evidence. POSITIVE ONLY, same reasoning as capability: absence of
-- evidence is not evidence of absence, and only an operator may assert a
-- negative.
CREATE TABLE IF NOT EXISTS catalog.category_assertion_machine (
    id                bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    product_uuid      uuid NOT NULL REFERENCES catalog.products (product_uuid),
    category          text NOT NULL REFERENCES catalog.software_category (key),
    source_key        text NOT NULL REFERENCES catalog.category_source (source_key),
    confidence        numeric(4,3) NOT NULL,
    evidence_kind     text NOT NULL,
    evidence_ref      text NOT NULL DEFAULT '',
    matcher_version   text NOT NULL,
    first_observed_at timestamptz NOT NULL DEFAULT now(),
    last_observed_at  timestamptz NOT NULL DEFAULT now(),
    withdrawn_at      timestamptz,
    withdrawn_reason  text NOT NULL DEFAULT '',
    CONSTRAINT ck_cat_am_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_cat_am_withdrawn_reason CHECK (
        (withdrawn_at IS NULL AND withdrawn_reason = '')
        OR (withdrawn_at IS NOT NULL AND withdrawn_reason <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cat_am_current
    ON catalog.category_assertion_machine (product_uuid, category, source_key)
    WHERE withdrawn_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_cat_am_lookup
    ON catalog.category_assertion_machine (product_uuid, category)
    WHERE withdrawn_at IS NULL;

-- Operator assertions. Carry polarity: a human may assert a product is NOT a
-- category, and that negative must persist so a rejected candidate does not
-- reappear every enrichment cycle.
CREATE TABLE IF NOT EXISTS catalog.category_assertion_operator (
    id               bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    product_uuid     uuid NOT NULL REFERENCES catalog.products (product_uuid),
    category         text NOT NULL REFERENCES catalog.software_category (key),
    polarity         boolean NOT NULL,
    rationale        text NOT NULL DEFAULT '',
    confirmed_by     text NOT NULL,
    confirmed_at     timestamptz NOT NULL DEFAULT now(),
    withdrawn_at     timestamptz,
    withdrawn_reason text NOT NULL DEFAULT '',
    CONSTRAINT ck_cat_ao_actor CHECK (confirmed_by <> ''),
    CONSTRAINT ck_cat_ao_withdrawn_reason CHECK (
        (withdrawn_at IS NULL AND withdrawn_reason = '')
        OR (withdrawn_at IS NOT NULL AND withdrawn_reason <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cat_ao_current
    ON catalog.category_assertion_operator (product_uuid, category)
    WHERE withdrawn_at IS NULL;

-- ---------------------------------------------------------------------------
-- Effective relation. Same precedence shape as capability's, minus the
-- alertable axis, which does not exist here.
--
--   operator negative -> 'refuted' (overrides every machine positive)
--   operator positive -> 'confirmed'
--   machine positive   -> 'candidate' (there is no vetted tier here at all --
--                          every source in category_source is a community
--                          tag, so nothing can ever be more than a candidate
--                          without an operator confirming it)
--   no row at all      -> absent, i.e. unknown
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW catalog.v_product_category_effective AS
WITH operator_current AS (
    SELECT product_uuid, category, polarity, confirmed_by, confirmed_at
      FROM catalog.category_assertion_operator
     WHERE withdrawn_at IS NULL
),
machine_current AS (
    SELECT m.product_uuid,
           m.category,
           max(m.confidence) AS best_confidence,
           string_agg(DISTINCT m.source_key, ',' ORDER BY m.source_key) AS source_keys
      FROM catalog.category_assertion_machine m
      JOIN catalog.category_source s ON s.source_key = m.source_key
     WHERE m.withdrawn_at IS NULL
       AND s.enabled
     GROUP BY m.product_uuid, m.category
)
SELECT
    COALESCE(o.product_uuid, m.product_uuid) AS product_uuid,
    COALESCE(o.category,     m.category)     AS category,
    CASE
        WHEN o.polarity IS FALSE THEN 'refuted'
        WHEN o.polarity IS TRUE  THEN 'confirmed'
        ELSE 'candidate'
    END AS state,
    CASE WHEN o.product_uuid IS NOT NULL THEN 'operator' ELSE m.source_keys END
        AS evidence_sources,
    m.best_confidence,
    o.confirmed_by,
    o.confirmed_at
FROM operator_current o
FULL OUTER JOIN machine_current m
  ON m.product_uuid = o.product_uuid AND m.category = o.category;

-- ── Grants ──────────────────────────────────────────────────────────────────
-- Same ownership note as 093: ingest connects as `ninja` (superuser), so the
-- ingest -> operator direction is enforced by review and tests, not by the
-- database, until that changes. Grants below are written as though ingest
-- were `ninja_ingest` so they begin enforcing the moment it is.

REVOKE ALL ON catalog.software_category            FROM PUBLIC;
REVOKE ALL ON catalog.category_source               FROM PUBLIC;
REVOKE ALL ON catalog.category_tag_rule             FROM PUBLIC;
REVOKE ALL ON catalog.category_assertion_machine    FROM PUBLIC;
REVOKE ALL ON catalog.category_assertion_operator   FROM PUBLIC;

-- Registry and tag rules are migration-managed: nobody writes them at runtime.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.software_category, catalog.category_source, catalog.category_tag_rule
  FROM operations_app, ninja_ingest;

GRANT SELECT ON catalog.software_category, catalog.category_source,
                catalog.category_tag_rule
   TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

-- Machine evidence: ingest writes, Operations reads.
GRANT SELECT, INSERT ON catalog.category_assertion_machine TO ninja_ingest;
GRANT UPDATE (last_observed_at, confidence, evidence_kind, evidence_ref,
              matcher_version, withdrawn_at, withdrawn_reason)
    ON catalog.category_assertion_machine TO ninja_ingest;
GRANT SELECT ON catalog.category_assertion_machine
   TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.category_assertion_machine FROM operations_app;

-- Operator assertions: Operations writes, ingest reads. UPDATE is
-- column-level, limited to the withdrawal pair -- a conclusion is history,
-- correcting one means withdrawing and inserting a new row, same as
-- capability_assertion_operator.
GRANT SELECT, INSERT ON catalog.category_assertion_operator TO operations_app;
GRANT UPDATE (withdrawn_at, withdrawn_reason)
    ON catalog.category_assertion_operator TO operations_app;
GRANT SELECT ON catalog.category_assertion_operator
   TO operations_readonly, metabase_ro, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.category_assertion_operator FROM ninja_ingest;

-- Nothing deletes evidence. Withdrawal is a timestamp plus a reason.
REVOKE DELETE, TRUNCATE
    ON catalog.category_assertion_machine, catalog.category_assertion_operator
  FROM operations_app, ninja_ingest;

GRANT USAGE, SELECT ON SEQUENCE
    catalog.category_assertion_machine_id_seq TO ninja_ingest;
GRANT USAGE, SELECT ON SEQUENCE
    catalog.category_assertion_operator_id_seq TO operations_app;
GRANT USAGE, SELECT ON SEQUENCE
    catalog.category_tag_rule_id_seq TO ninja_ingest;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.v_product_category_effective
  FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON catalog.v_product_category_effective
   TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

COMMENT ON TABLE catalog.category_assertion_machine IS
    'Machine-derived category evidence from community package tags, positive '
    'only. Never alerts -- there is no unauthorized_<category> finding.';
COMMENT ON TABLE catalog.category_assertion_operator IS
    'Human category confirmations and rejections. Rejections persist as '
    'authoritative negatives so a rejected candidate does not reappear.';
COMMENT ON VIEW catalog.v_product_category_effective IS
    'Single resolution used by the classifier and UI. No row means unknown, '
    'reported as unknown rather than as uncategorized-and-safe-to-ignore.';
