-- 080: derive which devices are exposed to each software finding.
--
-- Once a finding's subject is the title or the release, "which devices does
-- this affect" is no longer stored -- it is a join through the installation
-- relationship. That is the point: one finding on a title, 1,378 exposed
-- devices, and patching the title fleet-wide resolves one row instead of
-- 1,378.
--
-- Exposure is derived, never stored. Nothing writes this view, and a device
-- gaining or losing an installation changes its exposure on the next read
-- with no reconciliation step.
--
-- Approval tiers resolve here rather than as stored rows:
--   * global approve  -> the finding itself resolves; it never reaches this
--                        view, because only open findings are selected.
--   * client approve  -> the finding stays open; that client's devices drop
--                        out below.
--   * device approve  -> the finding stays open; that device drops out.
-- Only the global tier closes a finding. The narrower two are filters on
-- derived exposure, which is why they need no finding rows of their own.

CREATE OR REPLACE VIEW operations.v_device_software_exposure
WITH (security_barrier = true) AS
WITH software_findings AS (
    SELECT f.id AS finding_id,
           f.tenant_id,
           f.finding_type_id,
           f.subject_type,
           f.subject_id,
           f.severity,
           f.status,
           f.first_seen_at,
           f.last_seen_at,
           f.finding_details,
           ft.name AS finding_type
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE f.subject_type IN ('software_product', 'software_version')
       AND f.status IN ('open', 'acknowledged', 'investigating')
),
-- A product-scoped finding reaches every version of that product; a
-- version-scoped one reaches exactly its own release.
exposed AS (
    SELECT sf.*, sv.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.products p         ON p.product_uuid = sf.subject_id
      JOIN catalog.software_versions sv ON sv.product_id = p.id
     WHERE sf.subject_type = 'software_product'
    UNION ALL
    SELECT sf.*, sv.id AS software_version_id
      FROM software_findings sf
      JOIN catalog.software_versions sv ON sv.version_uuid = sf.subject_id
     WHERE sf.subject_type = 'software_version'
)
SELECT e.finding_id,
       e.tenant_id,
       e.finding_type_id,
       e.finding_type,
       e.subject_type,
       e.subject_id,
       e.severity,
       e.status,
       e.first_seen_at,
       e.last_seen_at,
       e.finding_details,
       sic.device_id,
       sic.client_id,
       sic.canonical_name,
       sic.publisher,
       sic.install_location,
       sic.install_date,
       sv.version
  FROM exposed e
  JOIN operations.software_installations_current sic
    ON sic.software_version_id = e.software_version_id
   AND sic.tenant_id           = e.tenant_id
  JOIN catalog.software_versions sv ON sv.id = e.software_version_id
 WHERE sic.stale_since IS NULL
   AND sic.deleted_at IS NULL
   -- Device-tier approval: this machine is allowed to run it.
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = sic.tenant_id
           AND sd.device_id = sic.device_id
           AND sd.decision IN ('approve', 'approve_publisher')
           AND (
                (sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = sic.publisher)
           )
   )
   -- Client-tier approval: this client is allowed to run it anywhere.
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = sic.tenant_id
           AND sd.client_id = sic.client_id
           AND sd.device_id IS NULL
           AND sd.decision IN ('approve', 'approve_publisher')
           AND (
                (sd.canonical_name <> '' AND sd.canonical_name = sic.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = sic.publisher)
           )
   );

-- operations/AGENTS.md: a migration creating a view in `operations` must
-- explicitly revoke DML from the runtime roles. ALTER DEFAULT PRIVILEGES grants
-- operations_app full DML on everything operations_migrate creates, and
-- PostgreSQL has no default-privilege object type separating views from tables.
-- Most such grants are inert, but a security_barrier view that is
-- auto-updatable executes DML as its owner -- migration 0122 found exactly that
-- handing the application write access to tables denied to it. This view has a
-- UNION and a WITH, so it is not auto-updatable, but the revoke is
-- unconditional because that property is not something a future edit should
-- have to preserve silently.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_device_software_exposure
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_device_software_exposure
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON VIEW operations.v_device_software_exposure IS
    'Derived: devices exposed to each open software finding, through the '
    'installation relationship, minus client- and device-tier approvals. '
    'Never written. A global approval resolves the finding itself and so '
    'removes it from this view entirely.';
