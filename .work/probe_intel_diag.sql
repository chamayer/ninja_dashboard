\pset pager off
SELECT connector, last_status, LEFT(last_error, 300) AS last_error, notes
FROM operations.intel_ingest_status
ORDER BY last_status <> 'ok' DESC, connector;

-- Sample canonical names + normalized (matcher-side) tokens
SELECT canonical_name,
       LOWER(REGEXP_REPLACE(canonical_name, '[^a-zA-Z0-9]+', '', 'g')) AS matcher_token
FROM operations.software_installations_current
WHERE tenant_id=1 AND deleted_at IS NULL AND stale_since IS NULL
GROUP BY canonical_name
ORDER BY canonical_name
LIMIT 12;

-- Sample of CPE products
SELECT vendor, product FROM intel.cpes
WHERE product ~ '^(chrome|firefox|edge|office|zoom|slack|teams|adobe|acrobat)$'
LIMIT 20;

-- Do any of our common product tokens match CPE products?
SELECT
    (SELECT COUNT(*) FROM intel.cpes WHERE LOWER(product)='chrome')     AS chrome_cpes,
    (SELECT COUNT(*) FROM intel.cpes WHERE LOWER(product)='firefox')    AS firefox_cpes,
    (SELECT COUNT(*) FROM intel.cpes WHERE LOWER(product)='office')     AS office_cpes,
    (SELECT COUNT(*) FROM intel.cpes WHERE LOWER(product)='acrobat_reader') AS reader_cpes;
