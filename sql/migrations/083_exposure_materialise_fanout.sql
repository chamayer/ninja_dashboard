-- 083: split device software exposure into a materialised fan-out plus a live
-- approval filter.
--
-- Measured 2026-08-10 against a simulated re-emission of 3,768 product-scoped
-- and 944 release-scoped findings (deliberately ~2.6x the measured real set):
--
--   full view, with approval filters      6.4 s
--   same joins, approval filters removed  3.3 s   -> 446,806 rows
--   decisions queue over it              10.6 s
--   client workspace rollup               8.3 s
--   org software page, one client         4.1 s
--
-- The cost splits almost evenly. ~3.3 s is the fan-out itself -- a bitmap heap
-- scan of software_installations_current run 19,186 times, touching ~451k heap
-- blocks -- and ~3.0 s is the two approval NOT EXISTS subqueries.
--
-- Indexing alone cannot fix it: software_decisions already carries 11 indexes
-- including (tenant_id, device_id, canonical_name) and
-- (tenant_id, client_id, canonical_name), and removing the approval half
-- entirely still leaves 3.3 s.
--
-- So the expensive, slow-changing half is materialised and the half that must
-- react instantly is not. Materialising the *whole* view would have been
-- simpler and would have broken the design: a client- or device-tier approval
-- is meant to remove exposure immediately, and would instead have waited for
-- the next refresh.

DROP VIEW IF EXISTS operations.v_device_software_exposure;

-- The fan-out: which devices run the software each open finding is about.
-- Contains no approval logic, so it only changes when findings or
-- installations change -- both of which already have explicit producers.
CREATE MATERIALIZED VIEW IF NOT EXISTS operations.v_device_software_exposure_base AS
WITH software_findings AS (
    SELECT f.id AS finding_id, f.tenant_id, f.finding_type_id, f.subject_type,
           f.subject_id, f.severity, f.status, f.first_seen_at, f.last_seen_at,
           f.finding_details, ft.name AS finding_type
      FROM operations.findings f
      JOIN operations.finding_types ft ON ft.id = f.finding_type_id
     WHERE f.subject_type IN ('software_product', 'software_version')
       AND f.status IN ('open', 'acknowledged', 'investigating')
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
   AND sic.deleted_at IS NULL;

-- Every access path the rewired surfaces use.
CREATE INDEX IF NOT EXISTS exposure_base_device_idx
    ON operations.v_device_software_exposure_base (tenant_id, device_id);
CREATE INDEX IF NOT EXISTS exposure_base_client_idx
    ON operations.v_device_software_exposure_base (tenant_id, client_id);
CREATE INDEX IF NOT EXISTS exposure_base_finding_idx
    ON operations.v_device_software_exposure_base (finding_id);
CREATE INDEX IF NOT EXISTS exposure_base_canonical_idx
    ON operations.v_device_software_exposure_base (tenant_id, canonical_name);
-- Supports the approval anti-joins below.
CREATE INDEX IF NOT EXISTS exposure_base_approval_idx
    ON operations.v_device_software_exposure_base
       (tenant_id, device_id, canonical_name, publisher);

-- The live half. Same name and same columns as before, so every consumer is
-- unchanged. Approvals are evaluated on read, so a client or device decision
-- still removes exposure the moment it is saved.
CREATE OR REPLACE VIEW operations.v_device_software_exposure
WITH (security_barrier = true) AS
SELECT b.*
  FROM operations.v_device_software_exposure_base b
 WHERE NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = b.tenant_id
           AND sd.device_id = b.device_id
           AND sd.decision IN ('approve', 'approve_publisher')
           AND ((sd.canonical_name <> '' AND sd.canonical_name = b.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = b.publisher))
   )
   AND NOT EXISTS (
        SELECT 1 FROM operations.software_decisions sd
         WHERE sd.tenant_id = b.tenant_id
           AND sd.client_id = b.client_id
           AND sd.device_id IS NULL
           AND sd.decision IN ('approve', 'approve_publisher')
           AND ((sd.canonical_name <> '' AND sd.canonical_name = b.canonical_name)
             OR (sd.publisher      <> '' AND sd.publisher      = b.publisher))
   );

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_device_software_exposure,
       operations.v_device_software_exposure_base
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_device_software_exposure,
                operations.v_device_software_exposure_base
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON MATERIALIZED VIEW operations.v_device_software_exposure_base IS
    'Fan-out only: which devices run the software each open finding is about. '
    'No approval logic -- refreshed by the software classifier after it emits. '
    'Read operations.v_device_software_exposure instead, which applies '
    'client- and device-tier approvals live.';

-- One consumer aggregates the *entire* exposure set rather than reading a
-- slice of it: the all-clients directory rollup in client_workspace.py.
-- Measured on the same simulated load, that query costs 8.6s against the live
-- view and 12.9s against the matview above -- materialising the fan-out makes
-- its 776,646 rows explicit, so the two approval anti-joins run per row.
--
-- Every other surface reads a slice (one device, one client, one finding) and
-- is already sub-second. So the rollup gets its own pre-aggregated matview
-- rather than the whole design bending around it.
--
-- The trade, stated because it is real: approvals are applied when this is
-- built, so a client- or device-tier approval does not change these counts
-- until the next classifier run. That is acceptable *here specifically* --
-- these are directory-page counts, not the exposure list an operator acts on,
-- and v_device_software_exposure still applies approvals live for everything
-- that matters.
CREATE MATERIALIZED VIEW IF NOT EXISTS operations.v_client_software_issue_rollup AS
SELECT e.client_id,
       e.finding_type_id,
       e.severity,
       COUNT(DISTINCT (e.finding_id, e.device_id)) AS n,
       COUNT(DISTINCT e.device_id)                 AS subjects,
       COUNT(DISTINCT (e.finding_id, e.device_id))
           FILTER (WHERE e.first_seen_at >= now() - interval '24 hours') AS new
  FROM operations.v_device_software_exposure e
 WHERE e.tenant_id = 1
   AND e.status IN ('open', 'acknowledged', 'investigating')
 GROUP BY 1, 2, 3;

CREATE INDEX IF NOT EXISTS client_software_rollup_client_idx
    ON operations.v_client_software_issue_rollup (client_id);

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON operations.v_client_software_issue_rollup
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON operations.v_client_software_issue_rollup
    TO operations_app, operations_readonly, metabase_ro;

COMMENT ON MATERIALIZED VIEW operations.v_client_software_issue_rollup IS
    'Pre-aggregated software issue counts per client, for the client directory. '
    'Approvals are baked in at refresh time, so counts here lag an approval by '
    'one classifier run; read v_device_software_exposure for live exposure.';
