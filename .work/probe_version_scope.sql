\pset pager off
SET operations.tenant_id = 1;

-- 0. Join feasibility: column types must line up before any count means anything.
SELECT 'types' AS probe, table_name, column_name, data_type
  FROM information_schema.columns
 WHERE (table_schema, table_name, column_name) IN (
        ('operations','findings','subject_id'),
        ('operations','software_installations_current','device_id'),
        ('operations','software_installations_current','canonical_name'),
        ('operations','software_installations_current','version'),
        ('operations','software_installations_current','software_version_id'))
 ORDER BY table_name, column_name;

-- 1. THE QUESTION: for the two version-bound types, how many distinct
--    subjects at title scope vs at (title, version) scope?
--    Findings carry no version, so it is derived from the installation
--    row the finding was emitted from.
SELECT ft.name AS finding_type,
       COUNT(*)                                              AS open_rows,
       COUNT(DISTINCT lower(f.finding_details->>'canonical_name'))          AS by_title,
       COUNT(DISTINCT (lower(f.finding_details->>'canonical_name')
                       || '@' || COALESCE(sic.version,'')))                 AS by_title_version,
       COUNT(*) FILTER (WHERE sic.device_id IS NULL)          AS install_not_matched,
       COUNT(*) FILTER (WHERE sic.version IS NULL OR sic.version = '') AS matched_but_no_version
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
  LEFT JOIN operations.software_installations_current sic
         ON sic.tenant_id      = f.tenant_id
        AND sic.device_id      = f.subject_id
        AND sic.canonical_name = f.finding_details->>'canonical_name'
 WHERE ft.name IN ('eol_runtime','vulnerable_software')
   AND f.tenant_id = 1
   AND f.subject_type = 'device'
   AND f.status IN ('open','acknowledged')
 GROUP BY ft.name
 ORDER BY open_rows DESC;

-- 2. Control: same query for the five title-scoped types, to confirm the
--    plan's by_title numbers reproduce and that only 1 and 2 move.
SELECT ft.name AS finding_type,
       COUNT(*) AS open_rows,
       COUNT(DISTINCT lower(f.finding_details->>'canonical_name')) AS by_title,
       COUNT(DISTINCT (lower(f.finding_details->>'canonical_name')
                       || '@' || COALESCE(sic.version,''))) AS by_title_version
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
  LEFT JOIN operations.software_installations_current sic
         ON sic.tenant_id      = f.tenant_id
        AND sic.device_id      = f.subject_id
        AND sic.canonical_name = f.finding_details->>'canonical_name'
 WHERE ft.name IN ('whitelist_suggestion','suspicious_name',
                   'unauthorized_remote_access','unauthorized_av',
                   'known_malicious_hint')
   AND f.tenant_id = 1
   AND f.subject_type = 'device'
   AND f.status IN ('open','acknowledged')
 GROUP BY ft.name
 ORDER BY open_rows DESC;

-- 3. Version spread on the affected titles: is version-scoping even
--    discriminating, or does every install of these titles share one version?
SELECT ft.name AS finding_type,
       COUNT(*) AS affected_titles,
       SUM(CASE WHEN versions > 1 THEN 1 ELSE 0 END) AS titles_with_multiple_versions,
       MAX(versions) AS max_versions_on_one_title
  FROM (
    SELECT ft2.name, lower(f.finding_details->>'canonical_name') AS title,
           COUNT(DISTINCT COALESCE(sic.version,'')) AS versions
      FROM operations.findings f
      JOIN operations.finding_types ft2 ON ft2.id = f.finding_type_id
      LEFT JOIN operations.software_installations_current sic
             ON sic.tenant_id      = f.tenant_id
            AND sic.device_id      = f.subject_id
            AND sic.canonical_name = f.finding_details->>'canonical_name'
     WHERE ft2.name IN ('eol_runtime','vulnerable_software')
       AND f.tenant_id = 1 AND f.subject_type = 'device'
       AND f.status IN ('open','acknowledged')
     GROUP BY ft2.name, lower(f.finding_details->>'canonical_name')
  ) t
  JOIN operations.finding_types ft ON ft.name = t.name
 GROUP BY ft.name;

-- 4. Is there any version-level EOL data to bind to yet?
SELECT 'software_versions' AS probe,
       COUNT(*) AS rows,
       COUNT(*) FILTER (WHERE eol_date IS NOT NULL) AS with_eol_date,
       COUNT(DISTINCT product_id) AS distinct_products
  FROM catalog.software_versions;

-- 5. Catalog linkage coverage on the installs backing these findings.
SELECT COUNT(*) AS installs,
       COUNT(*) FILTER (WHERE software_version_id IS NOT NULL) AS linked
  FROM operations.software_installations_current
 WHERE tenant_id = 1;
