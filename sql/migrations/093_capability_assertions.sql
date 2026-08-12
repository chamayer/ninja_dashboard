-- 093: capability recognition -- evidence, authority, and one effective relation.
--
-- Recognises software with three operational capabilities (endpoint_security,
-- rmm, remote_access) precisely enough that an `unauthorized_*` finding can be
-- trusted. NOT a taxonomy: coverage is not the metric, precision is.
--
-- Measured 2026-08-12: 7 categorized titles of 21,995, so the detectors those
-- categories drive are a blind sensor rather than a clean fleet.
--
-- Three questions that must never share one field:
--   capability truth  -- what the software IS            (here, global)
--   policy sanctioning-- whether it is permitted HERE    (Phase 2, tenant)
--   trust             -- whether an operator approved it (software_decisions)
--
-- Placed in `catalog` beside products/software_versions: capability is a
-- property of the product, like `catalog.software_versions.eol_date`. Global,
-- no tenant, no RLS -- tenancy belongs to policy and trust, not to truth.
--
-- ---------------------------------------------------------------------------
-- OWNERSHIP AND THE WRITE BOUNDARY -- read before trusting the grants below.
--
-- Measured 2026-08-12: ingest connects as `ninja` with is_superuser = on;
-- Operations connects as `operations_app`, not a superuser. PostgreSQL
-- superusers bypass grants AND row security, including FORCE ROW LEVEL
-- SECURITY. Therefore:
--
--   Operations -> machine evidence : ENFORCED here (DML revoked).
--   ingest     -> operator rows    : NOT enforceable while ingest is superuser.
--
-- The second direction is held by code review and tests, not by the database.
-- The grants are written as though ingest were `ninja_ingest` so they begin
-- enforcing the moment that changes; running ingest as a non-superuser role is
-- recorded in .work/backlog.md and is worth doing well beyond this feature.
-- Claiming a structural boundary that does not exist would be worse than the
-- asymmetry itself.
-- ---------------------------------------------------------------------------

-- Vocabulary as data, so a fourth capability is an INSERT rather than a
-- redesign. ADR-0012 section 6.
CREATE TABLE IF NOT EXISTS catalog.capability (
    key         text PRIMARY KEY,
    label       text NOT NULL,
    description text NOT NULL DEFAULT ''
);

INSERT INTO catalog.capability (key, label, description) VALUES
    ('endpoint_security', 'Endpoint security',
     'AV/EDR/anti-malware. Named endpoint_security rather than av because '
     || 'installed inventory cannot prove an active protection engine.'),
    ('rmm', 'RMM / management',
     'Remote monitoring and management agents.'),
    ('remote_access', 'Remote access',
     'Interactive remote control and remote desktop tools.')
ON CONFLICT (key) DO NOTHING;

-- Authority is a registry row, never a column a projector writes about itself.
-- A connector must not be able to declare its own output alertable.
-- MACHINE sources only. There is deliberately no 'operator' row and no
-- 'operator' authority class: `capability_assertion_machine.source_key` is a
-- foreign key to this table, so an operator row here would let any machine
-- writer insert source_key='operator' and manufacture alertable evidence.
-- Operator precedence comes from the operator *table*, which the effective
-- view reads directly and which needs no registry entry.
CREATE TABLE IF NOT EXISTS catalog.capability_source (
    source_key      text PRIMARY KEY,
    authority_class text NOT NULL,
    may_alert       boolean NOT NULL,
    managed_by      text NOT NULL,
    enabled         boolean NOT NULL DEFAULT TRUE,
    notes           text NOT NULL DEFAULT '',
    CONSTRAINT ck_capability_source_authority CHECK (
        authority_class IN ('vetted_identity', 'vetted_rule',
                            'publisher_rule', 'community_tag')
    ),
    -- Authority and alerting are not independent knobs: only the two vetted
    -- classes may alert. Enforced so a later UPDATE cannot quietly promote a
    -- community tag into a security finding.
    CONSTRAINT ck_capability_source_may_alert CHECK (
        may_alert = (authority_class IN ('vetted_identity', 'vetted_rule'))
    )
);

INSERT INTO catalog.capability_source
    (source_key, authority_class, may_alert, managed_by, notes)
VALUES
    ('lolrmm',           'vetted_identity', TRUE,  'migration',
     'LOLRMM corpus, exact normalised tool-name match only (Phase 3).'),
    ('vetted_rule',      'vetted_rule',     TRUE,  'migration',
     'Narrow anchored product-name rules from catalog.capability_rule.'),
    ('publisher_rule',   'publisher_rule',  FALSE, 'migration',
     'Publisher patterns. Candidate evidence; never alerts.'),
    ('winget_tag',       'community_tag',   FALSE, 'migration',
     'Winget package tags. Candidate evidence; never alerts.'),
    ('chocolatey_tag',   'community_tag',   FALSE, 'migration',
     'Chocolatey package tags. Candidate evidence; never alerts.')
ON CONFLICT (source_key) DO NOTHING;

-- Machine evidence. POSITIVE ONLY -- there is no polarity column, because
-- machine negatives carry no authority: absence of evidence is not evidence of
-- absence. Only an operator may assert a negative, which is what stops a
-- rejected candidate reappearing every cycle.
CREATE TABLE IF NOT EXISTS catalog.capability_assertion_machine (
    id                bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    product_uuid      uuid    NOT NULL REFERENCES catalog.products (product_uuid),
    capability        text    NOT NULL REFERENCES catalog.capability (key),
    source_key        text    NOT NULL REFERENCES catalog.capability_source (source_key),
    confidence        numeric(4,3) NOT NULL,
    evidence_kind     text    NOT NULL,
    evidence_ref      text    NOT NULL DEFAULT '',
    matcher_version   text    NOT NULL,
    first_observed_at timestamptz NOT NULL DEFAULT now(),
    last_observed_at  timestamptz NOT NULL DEFAULT now(),
    withdrawn_at      timestamptz,
    withdrawn_reason  text    NOT NULL DEFAULT '',
    CONSTRAINT ck_cam_confidence CHECK (confidence >= 0 AND confidence <= 1),
    -- ADR-0012: nothing is lost without when AND why.
    CONSTRAINT ck_cam_withdrawn_reason CHECK (
        (withdrawn_at IS NULL AND withdrawn_reason = '')
        OR (withdrawn_at IS NOT NULL AND withdrawn_reason <> '')
    )
);

-- One current row per source per product per capability. Withdrawn rows are
-- history and may repeat, so the index is partial: a capability that goes away
-- and returns leaves both episodes visible.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cam_current
    ON catalog.capability_assertion_machine (product_uuid, capability, source_key)
    WHERE withdrawn_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_cam_lookup
    ON catalog.capability_assertion_machine (product_uuid, capability)
    WHERE withdrawn_at IS NULL;

-- Operator assertions. These DO carry polarity: a human may assert that
-- something is not a capability, and that negative must persist.
CREATE TABLE IF NOT EXISTS catalog.capability_assertion_operator (
    id               bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    product_uuid     uuid    NOT NULL REFERENCES catalog.products (product_uuid),
    capability       text    NOT NULL REFERENCES catalog.capability (key),
    polarity         boolean NOT NULL,
    rationale        text    NOT NULL DEFAULT '',
    confirmed_by     text    NOT NULL,
    confirmed_at     timestamptz NOT NULL DEFAULT now(),
    withdrawn_at     timestamptz,
    withdrawn_reason text    NOT NULL DEFAULT '',
    CONSTRAINT ck_cao_actor CHECK (confirmed_by <> ''),
    CONSTRAINT ck_cao_withdrawn_reason CHECK (
        (withdrawn_at IS NULL AND withdrawn_reason = '')
        OR (withdrawn_at IS NOT NULL AND withdrawn_reason <> '')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cao_current
    ON catalog.capability_assertion_operator (product_uuid, capability)
    WHERE withdrawn_at IS NULL;

-- Anchored product-name rules, migration-seeded. Patterns are anchored by
-- policy: the EOL work measured what substring matching costs -- `Intel(R)
-- Trusted Connect Services Client` matching `rust`.
CREATE TABLE IF NOT EXISTS catalog.capability_rule (
    rule_key          text PRIMARY KEY,
    capability        text NOT NULL REFERENCES catalog.capability (key),
    title_pattern     text NOT NULL DEFAULT '',
    publisher_pattern text NOT NULL DEFAULT '',
    source_key        text NOT NULL REFERENCES catalog.capability_source (source_key),
    priority          int  NOT NULL DEFAULT 100,
    enabled           boolean NOT NULL DEFAULT TRUE,
    notes             text NOT NULL DEFAULT '',
    CONSTRAINT ck_capability_rule_has_a_pattern CHECK (
        title_pattern <> '' OR publisher_pattern <> ''
    ),
    -- A leading wildcard is how a title inherits the wrong capability. Both
    -- SQL wildcards are rejected: `_` matches one character, so '_hrome' is
    -- every bit as loose an anchor as '%chrome'.
    CONSTRAINT ck_capability_rule_anchored CHECK (
        title_pattern     NOT LIKE '\%%' AND title_pattern     NOT LIKE '\_%'
    AND publisher_pattern NOT LIKE '\%%' AND publisher_pattern NOT LIKE '\_%'
    ),
    -- This table drives exactly two sources. Without this a rule could claim
    -- `lolrmm`, whose evidence is supposed to come from the corpus connector
    -- and be an exact identity match rather than a pattern.
    CONSTRAINT ck_capability_rule_source CHECK (
        source_key IN ('vetted_rule', 'publisher_rule')
    ),
    -- A publisher pattern alone is not identity. Without this, a rule matching
    -- only `%Microsoft%` could claim `vetted_rule` and become alertable,
    -- raising unauthorized findings across a publisher's entire catalogue.
    CONSTRAINT ck_capability_rule_vetted_needs_a_title CHECK (
        source_key <> 'vetted_rule' OR title_pattern <> ''
    )
);

CREATE INDEX IF NOT EXISTS idx_capability_rule_order
    ON catalog.capability_rule (enabled, priority, rule_key);

-- ---------------------------------------------------------------------------
-- The effective relation. One definition, consumed by both the classifier and
-- the UI, so resolution cannot drift between Python and SQL.
--
-- Precedence:
--   operator negative -> false, terminal (overrides every machine positive)
--   operator positive -> true, alertable
--   machine positive from a may_alert source -> true, alertable
--   machine positive otherwise               -> true, candidate (never alerts)
--   no row at all                            -> absent, i.e. UNKNOWN
--
-- Unknown is deliberately not a row. Absence means unknown and must be
-- reported as unknown, not as safe.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW catalog.v_product_capability_effective AS
WITH operator_current AS (
    SELECT product_uuid, capability, polarity, confirmed_by, confirmed_at
      FROM catalog.capability_assertion_operator
     WHERE withdrawn_at IS NULL
),
machine_current AS (
    -- `s.enabled` filters here, not inside the aggregate. Disabling a source
    -- must remove its evidence from effective truth entirely; filtering only
    -- inside has_alertable_source would silently downgrade it to a candidate
    -- and leave it asserting the capability.
    SELECT m.product_uuid,
           m.capability,
           bool_or(s.may_alert)                             AS has_alertable_source,
           max(m.confidence)                                AS best_confidence,
           string_agg(DISTINCT m.source_key, ',' ORDER BY m.source_key) AS source_keys
      FROM catalog.capability_assertion_machine m
      JOIN catalog.capability_source s ON s.source_key = m.source_key
     WHERE m.withdrawn_at IS NULL
       AND s.enabled
     GROUP BY m.product_uuid, m.capability
)
SELECT
    COALESCE(o.product_uuid, m.product_uuid) AS product_uuid,
    COALESCE(o.capability,   m.capability)   AS capability,
    CASE
        WHEN o.polarity IS FALSE THEN 'refuted'
        WHEN o.polarity IS TRUE  THEN 'confirmed'
        WHEN m.has_alertable_source           THEN 'asserted'
        ELSE 'candidate'
    END AS state,
    -- Only confirmed or vetted-machine evidence may drive an unauthorized_*
    -- finding. A refuted capability never alerts, whatever machines say.
    (o.polarity IS TRUE
     OR (o.polarity IS NULL AND COALESCE(m.has_alertable_source, FALSE)))
        AS alertable,
    CASE WHEN o.product_uuid IS NOT NULL THEN 'operator' ELSE m.source_keys END
        AS evidence_sources,
    m.best_confidence,
    o.confirmed_by,
    o.confirmed_at
FROM operator_current o
FULL OUTER JOIN machine_current m
  ON m.product_uuid = o.product_uuid AND m.capability = o.capability;

-- ── Grants ──────────────────────────────────────────────────────────────────
-- Schema catalog already grants USAGE to the four runtime roles (074) and sets
-- ALTER DEFAULT PRIVILEGES granting SELECT on new tables to operations_app,
-- operations_readonly and metabase_ro. Those defaults are relied on for reads;
-- everything below is the write boundary, stated explicitly.

REVOKE ALL ON catalog.capability                     FROM PUBLIC;
REVOKE ALL ON catalog.capability_source              FROM PUBLIC;
REVOKE ALL ON catalog.capability_rule                FROM PUBLIC;
REVOKE ALL ON catalog.capability_assertion_machine   FROM PUBLIC;
REVOKE ALL ON catalog.capability_assertion_operator  FROM PUBLIC;

-- Registry and vocabulary are migration-managed: nobody writes them at runtime.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.capability, catalog.capability_source, catalog.capability_rule
  FROM operations_app, ninja_ingest;

GRANT SELECT ON catalog.capability, catalog.capability_source,
                catalog.capability_rule
   TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

-- Machine evidence: ingest writes, Operations reads. This is the direction the
-- database can enforce today, because operations_app is not a superuser.
--
-- Column-level UPDATE for the same reason as the operator table: the projector
-- refreshes observation state and withdraws, it never rewrites which product a
-- piece of evidence was about. Inert while ingest is superuser; correct the
-- moment it is not.
GRANT SELECT, INSERT ON catalog.capability_assertion_machine TO ninja_ingest;
GRANT UPDATE (last_observed_at, confidence, evidence_kind, evidence_ref,
              matcher_version, withdrawn_at, withdrawn_reason)
    ON catalog.capability_assertion_machine TO ninja_ingest;
GRANT SELECT ON catalog.capability_assertion_machine
   TO operations_app, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.capability_assertion_machine FROM operations_app;

-- Operator assertions: Operations writes, ingest reads. See the ownership note
-- at the top -- the revoke from ninja_ingest is correct and currently inert,
-- because ingest connects as a superuser.
--
-- UPDATE is COLUMN-LEVEL, limited to the withdrawal pair. A conclusion is
-- history: changing one means withdrawing the old assertion and inserting a
-- new one, which keeps the actor, the timestamp and the original polarity
-- intact. Table-level UPDATE would let Operations rewrite polarity, product,
-- capability, confirming actor or confirmation time in place, leaving no trace
-- that a human ever said something different.
GRANT SELECT, INSERT ON catalog.capability_assertion_operator TO operations_app;
GRANT UPDATE (withdrawn_at, withdrawn_reason)
    ON catalog.capability_assertion_operator TO operations_app;
GRANT SELECT ON catalog.capability_assertion_operator
   TO operations_readonly, metabase_ro, ninja_ingest;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.capability_assertion_operator FROM ninja_ingest;

-- Nothing deletes evidence. Withdrawal is a timestamp plus a reason.
REVOKE DELETE, TRUNCATE
    ON catalog.capability_assertion_machine, catalog.capability_assertion_operator
  FROM operations_app, ninja_ingest;

GRANT USAGE, SELECT ON SEQUENCE
    catalog.capability_assertion_machine_id_seq TO ninja_ingest;
GRANT USAGE, SELECT ON SEQUENCE
    catalog.capability_assertion_operator_id_seq TO operations_app;

-- `operations_migrate` grants broad default view privileges.  This effective
-- read model is intended to be SELECT-only, so revoke DML explicitly rather
-- than relying on the view being non-updatable today.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON catalog.v_product_capability_effective
  FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
GRANT SELECT ON catalog.v_product_capability_effective
   TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

COMMENT ON TABLE catalog.capability_assertion_machine IS
    'Machine-derived capability evidence, positive only. Machine negatives '
    'carry no authority: absence of evidence is not evidence of absence.';
COMMENT ON TABLE catalog.capability_assertion_operator IS
    'Human capability confirmations and rejections. Rejections persist as '
    'authoritative negatives so a rejected candidate does not reappear.';
COMMENT ON VIEW catalog.v_product_capability_effective IS
    'Single resolution used by classifier and UI. No row means unknown, which '
    'must be reported as unknown rather than as safe.';
