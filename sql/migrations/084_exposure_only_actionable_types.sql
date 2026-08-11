-- 084: stop fanning review candidates across the fleet, and drop the
-- materialisation that only existed to carry them.
--
-- Measured 2026-08-10:
--
--   whitelist_suggestion (3,768 titles on >=10 devices)   446,807 exposure rows
--   every other title (17,627, <10 devices)                42,822
--   findings that actually describe device risk
--     (vulnerable + EOL reach)                              1,932 rows / 500 devices
--
-- 91% of the fan-out served one finding type -- and `whitelist_suggestion` is a
-- candidate for a *fleet-wide approval decision*, not a problem with any
-- machine. Three consumers already discarded it explicitly
-- (`finding_type <> 'whitelist_suggestion'`), and the fourth only wants a
-- count.
--
-- Migration 083 responded to the resulting 776,646 rows by materialising the
-- fan-out, which bought speed at the cost of two matviews, a ~31s refresh
-- coupled into the classifier, and client rollup counts that lagged an approval
-- by one run. Removing the rows removes all three. This supersedes 083.

-- Whether a finding of this type describes something about a *device*, or
-- something about the software that an operator decides once. A registry
-- column rather than a name test in SQL, for the same reason `subject_scope`
-- is one: ADR-0012 section 6, and `test_no_hardcoded_domain_mappings`.
--
-- Added here rather than in the Django migration because the view below reads
-- it, and the two migration runners have no ordering guarantee between them.
-- Django migration 0133 declares it to model state and issues no DDL.
ALTER TABLE operations.finding_types
    ADD COLUMN IF NOT EXISTS creates_device_exposure boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN operations.finding_types.creates_device_exposure IS
    'False when a finding of this type is about the software rather than any '
    'device running it, so it must not fan out across installations. '
    'whitelist_suggestion is the case this exists for: it asks "should we '
    'allow this title", which needs a device count, not a device list.';

UPDATE operations.finding_types
   SET creates_device_exposure = false
 WHERE name = 'whitelist_suggestion';

-- 083's materialisation is no longer needed: without the review candidates the
-- exposure set is small enough to compute live, which restores immediate
-- approval semantics everywhere with no exception to document.
DROP MATERIALIZED VIEW IF EXISTS operations.v_client_software_issue_rollup;
DROP VIEW IF EXISTS operations.v_device_software_exposure;
DROP MATERIALIZED VIEW IF EXISTS operations.v_device_software_exposure_base;

CREATE OR REPLACE VIEW operations.v_device_software_exposure
WITH (security_barrier = true) AS
WITH software_findings AS (
    SELECT f.id AS finding_id, f.tenant_id, f.finding_type_id, f.subject_type,
           f.subject_id, f.severity, f.status, f.first_seen_at, f.last_seen_at,
           f.finding_details, ft.name AS finding_type
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE f.subject_type IN ('software_product', 'software_version')
       AND f.status IN ('open', 'acknowledged', 'investigating')
       AND ft.creates_device_exposure
),
exposed AS (
    SELECT sf.*, sv.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.products p           ON p.product_uuid = sf.subject_id
      JOIN catalog.software_versions sv ON sv.product_id = p.id
     WHERE sf.subject_type = 'software_product'
    UNION ALL
    SELECT sf.*, sv.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.software_versions sv ON sv.version_uuid = sf.subject_id
     WHERE sf.subject_type = 'software_version'
)
SELECT e.finding_id, e.tenant_id, e.finding_type_id, e.finding_type,
       e.subject_type, e.subject_id, e.severity, e.status,
       e.first_seen_at, e.last_seen_at, e.finding_details,
       sic.device_id, sic.client_id, sic.canonical_name, sic.publisher,
       sic.install_location, sic.install_date, sv.version
  FROM exposed e
  JOIN operations.software_installations_current sic
    ON sic.software_version_id = e.software_version_id
   AND sic.tenant_id           = e.tenant_id
  JOIN catalog.software_versions sv ON sv.id = e.software_version_id
 WHERE sic.stale_since IS NULL
   AND sic.deleted_at IS NULL
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = sic.tenant_id
           AND sd.device_id = sic.device_id
           AND sd.decision IN ('approve', 'approve_publisher')
           AND ((sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = sic.publisher))
   )
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = sic.tenant_id
           AND sd.client_id = sic.client_id
           AND sd.device_id IS NULL
           AND sd.decision IN ('approve', 'approve_publisher')
           AND ((sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = sic.publisher))
   );

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_device_software_exposure
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_device_software_exposure
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON VIEW operations.v_device_software_exposure IS
    'Devices exposed to each open software finding, through the installation '
    'relationship, minus client- and device-tier approvals, and excluding '
    'finding types that describe the software rather than the device. Live, '
    'never materialised: approvals take effect immediately.';
