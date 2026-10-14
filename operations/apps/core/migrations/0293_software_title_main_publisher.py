"""Show a title's main publisher, not its alphabetically last.

``operations.software_title_current`` picked ``max(publisher)`` for each title.
For a title with several publisher strings that is the alphabetically last, so
Cyrillic beat Latin ("Microsoft Edge" listed "Корпорация Майкрософт" although
4,419 of 4,422 installs say "Microsoft Corporation"). 301 of 514 multi-publisher
titles showed a non-main publisher. The view now takes the most common publisher
(``mode()``; ties by name), the same choice the software review facts make.

``operations.v_software_safety`` is the only object that depends on the title
view, so both are recreated: same columns, indexes (the unique index keeps
``REFRESH ... CONCURRENTLY`` working), grants, and owner. Write privileges are
revoked explicitly, as the module's migration rules require. The safety view's
definition is the live one, captured from production on 2026-10-14.
"""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DROP MATERIALIZED VIEW operations.v_software_safety;
DROP MATERIALIZED VIEW operations.software_title_current;
CREATE MATERIALIZED VIEW operations.software_title_current AS
SELECT sic.tenant_id,
       sic.canonical_name,
       mode() WITHIN GROUP (ORDER BY sic.publisher) AS publisher,
       COUNT(*)::integer AS installations,
       COUNT(DISTINCT sic.device_id)::integer AS device_count,
       COUNT(DISTINCT sic.client_id)::integer AS client_count,
       MIN(sic.first_observed_at) AS first_observed_at,
       MAX(sic.last_observed_at) AS last_observed_at,
       MAX(sic.first_observed_at) AS latest_install
FROM operations.software_installations_current sic
WHERE sic.deleted_at IS NULL AND sic.stale_since IS NULL
GROUP BY sic.tenant_id, sic.canonical_name
WITH DATA;
CREATE UNIQUE INDEX software_title_current_pk
    ON operations.software_title_current (tenant_id, canonical_name);
CREATE INDEX software_title_current_publisher_idx
    ON operations.software_title_current (tenant_id, LOWER(publisher));
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.software_title_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.software_title_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.software_title_current OWNER TO operations_migrate;
CREATE MATERIALIZED VIEW operations.v_software_safety AS
WITH per_title_cves AS (
         SELECT cm.tenant_id,
            cm.canonical_name,
            count(DISTINCT cm.cve_id) AS cve_count,
            count(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag) AS kev_count,
            count(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS cve_count_recent,
            max(c.cvss_v3) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS max_cvss_recent,
            max(c.cvss_v3) AS max_cvss,
            max(c.epss_score) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS max_epss_recent,
            max(c.epss_score) AS max_epss
           FROM operations.cve_match cm
             LEFT JOIN intel.cves c ON c.cve_id = cm.cve_id
          GROUP BY cm.tenant_id, cm.canonical_name
        ), per_title_osint AS (
         SELECT safety_signal.tenant_id,
            safety_signal.canonical_name,
            count(*) FILTER (WHERE safety_signal.signal_type = 'threat_hit'::text) AS threat_hits
           FROM operations.safety_signal
          WHERE safety_signal.canonical_name <> ''::text
          GROUP BY safety_signal.tenant_id, safety_signal.canonical_name
        ), per_publisher_osint AS (
         SELECT safety_signal.tenant_id,
            lower(safety_signal.publisher) AS publisher_lc,
            count(*) FILTER (WHERE safety_signal.signal_type = 'threat_hit'::text) AS pub_threat_hits
           FROM operations.safety_signal
          WHERE safety_signal.publisher <> ''::text
          GROUP BY safety_signal.tenant_id, (lower(safety_signal.publisher))
        ), title_decisions AS (
         SELECT software_decisions.tenant_id,
            lower(software_decisions.canonical_name::text) AS canonical_lc,
            bool_or(software_decisions.decision::text = ANY (ARRAY['approve'::character varying, 'approve_publisher'::character varying]::text[])) AS is_approved,
            bool_or(software_decisions.decision::text = 'reject'::text) AS is_rejected
           FROM operations.software_decisions
          WHERE software_decisions.canonical_name::text <> ''::text
          GROUP BY software_decisions.tenant_id, (lower(software_decisions.canonical_name::text))
        ), publisher_decisions AS (
         SELECT software_decisions.tenant_id,
            lower(software_decisions.publisher::text) AS publisher_lc,
            bool_or(software_decisions.decision::text = ANY (ARRAY['approve'::character varying, 'approve_publisher'::character varying]::text[])) AS is_approved,
            bool_or(software_decisions.decision::text = 'reject'::text) AS is_rejected
           FROM operations.software_decisions
          WHERE software_decisions.publisher::text <> ''::text
          GROUP BY software_decisions.tenant_id, (lower(software_decisions.publisher::text))
        ), publisher_alias_resolved AS (
         SELECT ft_1.tenant_id,
            ft_1.canonical_name,
            COALESCE(pa.canonical_publisher, ft_1.publisher::character varying) AS resolved_publisher
           FROM operations.software_title_current ft_1
             LEFT JOIN LATERAL ( SELECT publisher_aliases.canonical_publisher
                   FROM operations.publisher_aliases
                  WHERE publisher_aliases.enabled AND ft_1.publisher IS NOT NULL AND ft_1.publisher ~~* publisher_aliases.raw_pattern::text
                 LIMIT 1) pa ON true
        )
 SELECT ft.tenant_id,
    ft.canonical_name,
    ft.publisher,
    par.resolved_publisher,
    ft.installations,
    ft.device_count,
    ft.client_count,
    COALESCE(cve.cve_count, 0::bigint) AS cve_count,
    COALESCE(cve.kev_count, 0::bigint) AS kev_count,
    COALESCE(cve.cve_count_recent, 0::bigint) AS cve_count_recent,
    cve.max_cvss,
    cve.max_cvss_recent,
    cve.max_epss,
    cve.max_epss_recent,
    COALESCE(osint.threat_hits, 0::bigint) AS osint_hits,
    COALESCE(pub_osint.pub_threat_hits, 0::bigint) AS publisher_osint_hits,
    COALESCE(td.is_approved, false) AS title_approved,
    COALESCE(td.is_rejected, false) AS title_rejected,
    COALESCE(pd.is_approved, false) AS publisher_approved,
    COALESCE(pd.is_rejected, false) AS publisher_rejected,
    LEAST(100::numeric, GREATEST(0::numeric,
        CASE
            WHEN COALESCE(cve.kev_count, 0::bigint) > 0 THEN 100
            ELSE 0
        END::numeric + COALESCE(cve.max_cvss_recent, cve.max_cvss, 0::numeric) * 10::numeric + COALESCE(cve.max_epss_recent, cve.max_epss, 0::numeric) * 40::numeric + LEAST(30::bigint, COALESCE(osint.threat_hits, 0::bigint) * 10 + COALESCE(pub_osint.pub_threat_hits, 0::bigint) * 5)::numeric +
        CASE
            WHEN COALESCE(td.is_rejected, false) THEN 50
            ELSE 0
        END::numeric +
        CASE
            WHEN COALESCE(pd.is_rejected, false) THEN 30
            ELSE 0
        END::numeric -
        CASE
            WHEN COALESCE(td.is_approved, false) THEN 100
            ELSE 0
        END::numeric -
        CASE
            WHEN COALESCE(pd.is_approved, false) THEN 100
            ELSE 0
        END::numeric))::integer AS safety_score,
        CASE
            WHEN COALESCE(td.is_approved, false) OR COALESCE(pd.is_approved, false) THEN 'clean'::text
            WHEN COALESCE(cve.kev_count, 0::bigint) > 0 THEN 'high'::text
            WHEN COALESCE(cve.max_cvss_recent, 0::numeric) >= 7.0 THEN 'high'::text
            WHEN COALESCE(cve.max_cvss_recent, 0::numeric) >= 4.0 THEN 'medium'::text
            WHEN COALESCE(osint.threat_hits, 0::bigint) >= 3 THEN 'medium'::text
            WHEN COALESCE(osint.threat_hits, 0::bigint) > 0 OR COALESCE(pub_osint.pub_threat_hits, 0::bigint) > 0 THEN 'low'::text
            ELSE 'unknown'::text
        END AS safety_band
   FROM operations.software_title_current ft
     LEFT JOIN publisher_alias_resolved par ON par.tenant_id = ft.tenant_id AND par.canonical_name = ft.canonical_name
     LEFT JOIN per_title_cves cve ON cve.tenant_id = ft.tenant_id AND cve.canonical_name = ft.canonical_name
     LEFT JOIN per_title_osint osint ON osint.tenant_id = ft.tenant_id AND lower(osint.canonical_name) = lower(ft.canonical_name)
     LEFT JOIN per_publisher_osint pub_osint ON pub_osint.tenant_id = ft.tenant_id AND pub_osint.publisher_lc = lower(COALESCE(par.resolved_publisher, ft.publisher::character varying, ''::character varying)::text)
     LEFT JOIN title_decisions td ON td.tenant_id = ft.tenant_id AND td.canonical_lc = lower(ft.canonical_name)
     LEFT JOIN publisher_decisions pd ON pd.tenant_id = ft.tenant_id AND pd.publisher_lc = lower(COALESCE(par.resolved_publisher, ft.publisher::character varying, ''::character varying)::text)
WITH DATA;
CREATE UNIQUE INDEX v_software_safety_pk
    ON operations.v_software_safety (tenant_id, canonical_name);
CREATE INDEX v_software_safety_band_idx
    ON operations.v_software_safety (tenant_id, safety_band);
CREATE INDEX v_software_safety_publisher_idx
    ON operations.v_software_safety (tenant_id, LOWER(resolved_publisher));
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_software_safety
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_software_safety
    TO operations_app, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.v_software_safety OWNER TO operations_migrate;
"""

REVERSE_SQL = r"""
DROP MATERIALIZED VIEW operations.v_software_safety;
DROP MATERIALIZED VIEW operations.software_title_current;
CREATE MATERIALIZED VIEW operations.software_title_current AS
SELECT sic.tenant_id,
       sic.canonical_name,
       MAX(sic.publisher) AS publisher,
       COUNT(*)::integer AS installations,
       COUNT(DISTINCT sic.device_id)::integer AS device_count,
       COUNT(DISTINCT sic.client_id)::integer AS client_count,
       MIN(sic.first_observed_at) AS first_observed_at,
       MAX(sic.last_observed_at) AS last_observed_at,
       MAX(sic.first_observed_at) AS latest_install
FROM operations.software_installations_current sic
WHERE sic.deleted_at IS NULL AND sic.stale_since IS NULL
GROUP BY sic.tenant_id, sic.canonical_name
WITH DATA;
CREATE UNIQUE INDEX software_title_current_pk
    ON operations.software_title_current (tenant_id, canonical_name);
CREATE INDEX software_title_current_publisher_idx
    ON operations.software_title_current (tenant_id, LOWER(publisher));
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.software_title_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.software_title_current
    TO operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.software_title_current OWNER TO operations_migrate;
CREATE MATERIALIZED VIEW operations.v_software_safety AS
WITH per_title_cves AS (
         SELECT cm.tenant_id,
            cm.canonical_name,
            count(DISTINCT cm.cve_id) AS cve_count,
            count(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag) AS kev_count,
            count(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS cve_count_recent,
            max(c.cvss_v3) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS max_cvss_recent,
            max(c.cvss_v3) AS max_cvss,
            max(c.epss_score) FILTER (WHERE c.kev_flag OR c.last_modified_at > (now() - '3 years'::interval)) AS max_epss_recent,
            max(c.epss_score) AS max_epss
           FROM operations.cve_match cm
             LEFT JOIN intel.cves c ON c.cve_id = cm.cve_id
          GROUP BY cm.tenant_id, cm.canonical_name
        ), per_title_osint AS (
         SELECT safety_signal.tenant_id,
            safety_signal.canonical_name,
            count(*) FILTER (WHERE safety_signal.signal_type = 'threat_hit'::text) AS threat_hits
           FROM operations.safety_signal
          WHERE safety_signal.canonical_name <> ''::text
          GROUP BY safety_signal.tenant_id, safety_signal.canonical_name
        ), per_publisher_osint AS (
         SELECT safety_signal.tenant_id,
            lower(safety_signal.publisher) AS publisher_lc,
            count(*) FILTER (WHERE safety_signal.signal_type = 'threat_hit'::text) AS pub_threat_hits
           FROM operations.safety_signal
          WHERE safety_signal.publisher <> ''::text
          GROUP BY safety_signal.tenant_id, (lower(safety_signal.publisher))
        ), title_decisions AS (
         SELECT software_decisions.tenant_id,
            lower(software_decisions.canonical_name::text) AS canonical_lc,
            bool_or(software_decisions.decision::text = ANY (ARRAY['approve'::character varying, 'approve_publisher'::character varying]::text[])) AS is_approved,
            bool_or(software_decisions.decision::text = 'reject'::text) AS is_rejected
           FROM operations.software_decisions
          WHERE software_decisions.canonical_name::text <> ''::text
          GROUP BY software_decisions.tenant_id, (lower(software_decisions.canonical_name::text))
        ), publisher_decisions AS (
         SELECT software_decisions.tenant_id,
            lower(software_decisions.publisher::text) AS publisher_lc,
            bool_or(software_decisions.decision::text = ANY (ARRAY['approve'::character varying, 'approve_publisher'::character varying]::text[])) AS is_approved,
            bool_or(software_decisions.decision::text = 'reject'::text) AS is_rejected
           FROM operations.software_decisions
          WHERE software_decisions.publisher::text <> ''::text
          GROUP BY software_decisions.tenant_id, (lower(software_decisions.publisher::text))
        ), publisher_alias_resolved AS (
         SELECT ft_1.tenant_id,
            ft_1.canonical_name,
            COALESCE(pa.canonical_publisher, ft_1.publisher::character varying) AS resolved_publisher
           FROM operations.software_title_current ft_1
             LEFT JOIN LATERAL ( SELECT publisher_aliases.canonical_publisher
                   FROM operations.publisher_aliases
                  WHERE publisher_aliases.enabled AND ft_1.publisher IS NOT NULL AND ft_1.publisher ~~* publisher_aliases.raw_pattern::text
                 LIMIT 1) pa ON true
        )
 SELECT ft.tenant_id,
    ft.canonical_name,
    ft.publisher,
    par.resolved_publisher,
    ft.installations,
    ft.device_count,
    ft.client_count,
    COALESCE(cve.cve_count, 0::bigint) AS cve_count,
    COALESCE(cve.kev_count, 0::bigint) AS kev_count,
    COALESCE(cve.cve_count_recent, 0::bigint) AS cve_count_recent,
    cve.max_cvss,
    cve.max_cvss_recent,
    cve.max_epss,
    cve.max_epss_recent,
    COALESCE(osint.threat_hits, 0::bigint) AS osint_hits,
    COALESCE(pub_osint.pub_threat_hits, 0::bigint) AS publisher_osint_hits,
    COALESCE(td.is_approved, false) AS title_approved,
    COALESCE(td.is_rejected, false) AS title_rejected,
    COALESCE(pd.is_approved, false) AS publisher_approved,
    COALESCE(pd.is_rejected, false) AS publisher_rejected,
    LEAST(100::numeric, GREATEST(0::numeric,
        CASE
            WHEN COALESCE(cve.kev_count, 0::bigint) > 0 THEN 100
            ELSE 0
        END::numeric + COALESCE(cve.max_cvss_recent, cve.max_cvss, 0::numeric) * 10::numeric + COALESCE(cve.max_epss_recent, cve.max_epss, 0::numeric) * 40::numeric + LEAST(30::bigint, COALESCE(osint.threat_hits, 0::bigint) * 10 + COALESCE(pub_osint.pub_threat_hits, 0::bigint) * 5)::numeric +
        CASE
            WHEN COALESCE(td.is_rejected, false) THEN 50
            ELSE 0
        END::numeric +
        CASE
            WHEN COALESCE(pd.is_rejected, false) THEN 30
            ELSE 0
        END::numeric -
        CASE
            WHEN COALESCE(td.is_approved, false) THEN 100
            ELSE 0
        END::numeric -
        CASE
            WHEN COALESCE(pd.is_approved, false) THEN 100
            ELSE 0
        END::numeric))::integer AS safety_score,
        CASE
            WHEN COALESCE(td.is_approved, false) OR COALESCE(pd.is_approved, false) THEN 'clean'::text
            WHEN COALESCE(cve.kev_count, 0::bigint) > 0 THEN 'high'::text
            WHEN COALESCE(cve.max_cvss_recent, 0::numeric) >= 7.0 THEN 'high'::text
            WHEN COALESCE(cve.max_cvss_recent, 0::numeric) >= 4.0 THEN 'medium'::text
            WHEN COALESCE(osint.threat_hits, 0::bigint) >= 3 THEN 'medium'::text
            WHEN COALESCE(osint.threat_hits, 0::bigint) > 0 OR COALESCE(pub_osint.pub_threat_hits, 0::bigint) > 0 THEN 'low'::text
            ELSE 'unknown'::text
        END AS safety_band
   FROM operations.software_title_current ft
     LEFT JOIN publisher_alias_resolved par ON par.tenant_id = ft.tenant_id AND par.canonical_name = ft.canonical_name
     LEFT JOIN per_title_cves cve ON cve.tenant_id = ft.tenant_id AND cve.canonical_name = ft.canonical_name
     LEFT JOIN per_title_osint osint ON osint.tenant_id = ft.tenant_id AND lower(osint.canonical_name) = lower(ft.canonical_name)
     LEFT JOIN per_publisher_osint pub_osint ON pub_osint.tenant_id = ft.tenant_id AND pub_osint.publisher_lc = lower(COALESCE(par.resolved_publisher, ft.publisher::character varying, ''::character varying)::text)
     LEFT JOIN title_decisions td ON td.tenant_id = ft.tenant_id AND td.canonical_lc = lower(ft.canonical_name)
     LEFT JOIN publisher_decisions pd ON pd.tenant_id = ft.tenant_id AND pd.publisher_lc = lower(COALESCE(par.resolved_publisher, ft.publisher::character varying, ''::character varying)::text)
WITH DATA;
CREATE UNIQUE INDEX v_software_safety_pk
    ON operations.v_software_safety (tenant_id, canonical_name);
CREATE INDEX v_software_safety_band_idx
    ON operations.v_software_safety (tenant_id, safety_band);
CREATE INDEX v_software_safety_publisher_idx
    ON operations.v_software_safety (tenant_id, LOWER(resolved_publisher));
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_software_safety
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_software_safety
    TO operations_app, operations_readonly, metabase_ro;
ALTER MATERIALIZED VIEW operations.v_software_safety OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0292_software_routine_helper"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
