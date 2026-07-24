"""Composite safety score view for canonical software titles.

Combines the outputs of Batches B–D (intel.cves + operations.cve_match +
operations.safety_signal) with operator decisions into a single per-title
row the UI can render as a badge and a sortable column.

Weights are hard-coded in the view for now; ADR 0008 leaves room to
migrate them to EvaluatorConfig later.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE VIEW operations.v_software_safety AS
WITH per_title_cves AS (
    SELECT cm.tenant_id,
           cm.canonical_name,
           COUNT(DISTINCT cm.cve_id)                                AS cve_count,
           COUNT(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag)       AS kev_count,
           MAX(c.cvss_v3)                                            AS max_cvss,
           MAX(c.epss_score)                                         AS max_epss
      FROM operations.cve_match cm
      LEFT JOIN intel.cves c ON c.cve_id = cm.cve_id
     GROUP BY cm.tenant_id, cm.canonical_name
), per_title_osint AS (
    SELECT tenant_id,
           canonical_name,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit')                        AS threat_hits,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit' AND severity IN ('high','critical')) AS threat_hits_high,
           BOOL_OR(signal_type = 'threat_hit' AND severity IN ('high','critical'))    AS has_high_hit
      FROM operations.safety_signal
     WHERE canonical_name <> ''
     GROUP BY tenant_id, canonical_name
), per_publisher_osint AS (
    SELECT tenant_id,
           LOWER(publisher) AS publisher_lc,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit') AS pub_threat_hits
      FROM operations.safety_signal
     WHERE publisher <> ''
     GROUP BY tenant_id, LOWER(publisher)
), title_decisions AS (
    SELECT tenant_id,
           LOWER(canonical_name) AS canonical_lc,
           BOOL_OR(decision IN ('approve','approve_publisher'))     AS is_approved,
           BOOL_OR(decision = 'reject')                              AS is_rejected
      FROM operations.software_decisions
     WHERE canonical_name <> ''
     GROUP BY tenant_id, LOWER(canonical_name)
), publisher_decisions AS (
    SELECT tenant_id,
           LOWER(publisher) AS publisher_lc,
           BOOL_OR(decision IN ('approve','approve_publisher'))     AS is_approved,
           BOOL_OR(decision = 'reject')                              AS is_rejected
      FROM operations.software_decisions
     WHERE publisher <> ''
     GROUP BY tenant_id, LOWER(publisher)
), fleet_titles AS (
    SELECT sic.tenant_id,
           sic.canonical_name,
           MAX(sic.publisher)                       AS publisher,
           COUNT(*)::int                            AS installations,
           COUNT(DISTINCT sic.device_id)::int       AS device_count,
           COUNT(DISTINCT sic.client_id)::int       AS client_count
      FROM operations.software_installations_current sic
     WHERE sic.deleted_at IS NULL
       AND sic.stale_since IS NULL
     GROUP BY sic.tenant_id, sic.canonical_name
)
SELECT ft.tenant_id,
       ft.canonical_name,
       ft.publisher,
       ft.installations,
       ft.device_count,
       ft.client_count,
       COALESCE(cve.cve_count, 0)                       AS cve_count,
       COALESCE(cve.kev_count, 0)                       AS kev_count,
       cve.max_cvss                                     AS max_cvss,
       cve.max_epss                                     AS max_epss,
       COALESCE(osint.threat_hits, 0)                   AS osint_hits,
       COALESCE(pub_osint.pub_threat_hits, 0)           AS publisher_osint_hits,
       COALESCE(td.is_approved, FALSE)                  AS title_approved,
       COALESCE(td.is_rejected, FALSE)                  AS title_rejected,
       COALESCE(pd.is_approved, FALSE)                  AS publisher_approved,
       COALESCE(pd.is_rejected, FALSE)                  AS publisher_rejected,
       -- Composite: capped 0..100. Order of adds mirrors ADR 0008.
       LEAST(100, GREATEST(0,
            CASE WHEN COALESCE(cve.kev_count, 0) > 0 THEN 100 ELSE 0 END
          + COALESCE(cve.max_cvss, 0) * 10
          + COALESCE(cve.max_epss, 0) * 40
          + LEAST(30, COALESCE(osint.threat_hits, 0) * 10 + COALESCE(pub_osint.pub_threat_hits, 0) * 5)
          + CASE WHEN COALESCE(td.is_rejected, FALSE)     THEN 50 ELSE 0 END
          + CASE WHEN COALESCE(pd.is_rejected, FALSE)     THEN 30 ELSE 0 END
          - CASE WHEN COALESCE(td.is_approved, FALSE)     THEN 100 ELSE 0 END
          - CASE WHEN COALESCE(pd.is_approved, FALSE)     THEN 60 ELSE 0 END
       ))::int AS safety_score,
       CASE
         WHEN COALESCE(cve.kev_count, 0) > 0                             THEN 'high'
         WHEN COALESCE(cve.max_cvss, 0) >= 7.0                            THEN 'high'
         WHEN COALESCE(cve.max_cvss, 0) >= 4.0                            THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) >= 3                         THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) > 0
              OR COALESCE(pub_osint.pub_threat_hits, 0) > 0                THEN 'low'
         ELSE 'clean'
       END AS safety_band
  FROM fleet_titles ft
  LEFT JOIN per_title_cves     cve  ON cve.tenant_id = ft.tenant_id
                                    AND cve.canonical_name = ft.canonical_name
  LEFT JOIN per_title_osint    osint ON osint.tenant_id = ft.tenant_id
                                    AND LOWER(osint.canonical_name) = LOWER(ft.canonical_name)
  LEFT JOIN per_publisher_osint pub_osint ON pub_osint.tenant_id = ft.tenant_id
                                    AND pub_osint.publisher_lc = LOWER(COALESCE(ft.publisher, ''))
  LEFT JOIN title_decisions    td   ON td.tenant_id = ft.tenant_id
                                    AND td.canonical_lc = LOWER(ft.canonical_name)
  LEFT JOIN publisher_decisions pd  ON pd.tenant_id = ft.tenant_id
                                    AND pd.publisher_lc = LOWER(COALESCE(ft.publisher, ''));

GRANT SELECT ON operations.v_software_safety
   TO operations_app, operations_readonly, metabase_ro;
"""

REVERSE_SQL = "DROP VIEW IF EXISTS operations.v_software_safety;"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0080_whitelist_suggestion_finding_type"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
