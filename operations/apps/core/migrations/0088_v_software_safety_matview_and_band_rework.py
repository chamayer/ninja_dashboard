"""Convert ``operations.v_software_safety`` from a plain view into a
materialised view, and rework the risk-band logic so:

  * Publisher-scope APPROVE (or APPROVE_PUBLISHER) — via the resolved
    publisher alias — dominates the band. If the operator has
    accepted the publisher, no CVE / KEV signal should paint the
    product red.
  * A CVE match against an old release does not clip a currently-
    installed product's risk unless the CVE is either KEV-flagged or
    has been modified inside the last N years (default 3). Cumulative
    CVE counts from 2010-era Office CVEs are noise for modern
    installs. The full count is preserved as ``cve_count`` for the
    "informational" section on the title detail page.

The matview is refreshed at the end of the intel matcher and at
software-classify time; a ``REFRESH MATERIALIZED VIEW CONCURRENTLY``
call goes on the Software Decision write path (view refresh is fast
enough on the current fleet — 20 k rows).

Grants match sibling ninja_patches matviews (operations_app,
operations_readonly, metabase_ro).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

# Rows scored as "recent" — driving the risk band — must have been
# modified within the last ``_RECENCY_INTERVAL`` OR be KEV-flagged.
_RECENCY_INTERVAL = "3 years"

FORWARD_SQL = f"""
-- Drop the plain view; we're replacing with a matview of the same name.
DROP VIEW IF EXISTS operations.v_software_safety CASCADE;

CREATE MATERIALIZED VIEW operations.v_software_safety AS
WITH per_title_cves AS (
    SELECT cm.tenant_id,
           cm.canonical_name,
           COUNT(DISTINCT cm.cve_id)                                   AS cve_count,
           COUNT(DISTINCT cm.cve_id) FILTER (WHERE c.kev_flag)          AS kev_count,
           COUNT(DISTINCT cm.cve_id) FILTER (
               WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '{_RECENCY_INTERVAL}'
           )                                                            AS cve_count_recent,
           MAX(c.cvss_v3) FILTER (
               WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '{_RECENCY_INTERVAL}'
           )                                                            AS max_cvss_recent,
           MAX(c.cvss_v3)                                               AS max_cvss,
           MAX(c.epss_score) FILTER (
               WHERE c.kev_flag OR c.last_modified_at > NOW() - INTERVAL '{_RECENCY_INTERVAL}'
           )                                                            AS max_epss_recent,
           MAX(c.epss_score)                                            AS max_epss
      FROM operations.cve_match cm
      LEFT JOIN intel.cves c ON c.cve_id = cm.cve_id
     GROUP BY cm.tenant_id, cm.canonical_name
), per_title_osint AS (
    SELECT tenant_id, canonical_name,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit') AS threat_hits
      FROM operations.safety_signal
     WHERE canonical_name <> ''
     GROUP BY tenant_id, canonical_name
), per_publisher_osint AS (
    SELECT tenant_id, LOWER(publisher) AS publisher_lc,
           COUNT(*) FILTER (WHERE signal_type = 'threat_hit') AS pub_threat_hits
      FROM operations.safety_signal
     WHERE publisher <> ''
     GROUP BY tenant_id, LOWER(publisher)
), title_decisions AS (
    SELECT tenant_id, LOWER(canonical_name) AS canonical_lc,
           BOOL_OR(decision IN ('approve','approve_publisher')) AS is_approved,
           BOOL_OR(decision = 'reject') AS is_rejected
      FROM operations.software_decisions
     WHERE canonical_name <> ''
     GROUP BY tenant_id, LOWER(canonical_name)
), publisher_decisions AS (
    SELECT tenant_id, LOWER(publisher) AS publisher_lc,
           BOOL_OR(decision IN ('approve','approve_publisher')) AS is_approved,
           BOOL_OR(decision = 'reject') AS is_rejected
      FROM operations.software_decisions
     WHERE publisher <> ''
     GROUP BY tenant_id, LOWER(publisher)
), publisher_alias_resolved AS (
    -- Canonical publisher name per fleet product, via the admin
    -- PublisherAlias table. Falls back to the raw publisher when no
    -- alias applies. Raw string preserved on ``fleet_titles.publisher``.
    SELECT sic.tenant_id, sic.canonical_name,
           COALESCE(pa.canonical_publisher, sic.publisher) AS resolved_publisher
      FROM (
          SELECT DISTINCT tenant_id, canonical_name,
                 MAX(publisher) AS publisher
            FROM operations.software_installations_current
           WHERE deleted_at IS NULL AND stale_since IS NULL
           GROUP BY tenant_id, canonical_name
      ) sic
      LEFT JOIN LATERAL (
          SELECT canonical_publisher
            FROM operations.publisher_aliases
           WHERE enabled
             AND sic.publisher IS NOT NULL
             AND sic.publisher ILIKE raw_pattern
           LIMIT 1
      ) pa ON TRUE
), fleet_titles AS (
    SELECT sic.tenant_id, sic.canonical_name,
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
       par.resolved_publisher,
       ft.installations,
       ft.device_count,
       ft.client_count,
       COALESCE(cve.cve_count, 0)                       AS cve_count,
       COALESCE(cve.kev_count, 0)                       AS kev_count,
       COALESCE(cve.cve_count_recent, 0)                AS cve_count_recent,
       cve.max_cvss                                     AS max_cvss,
       cve.max_cvss_recent                              AS max_cvss_recent,
       cve.max_epss                                     AS max_epss,
       cve.max_epss_recent                              AS max_epss_recent,
       COALESCE(osint.threat_hits, 0)                   AS osint_hits,
       COALESCE(pub_osint.pub_threat_hits, 0)           AS publisher_osint_hits,
       COALESCE(td.is_approved, FALSE)                  AS title_approved,
       COALESCE(td.is_rejected, FALSE)                  AS title_rejected,
       COALESCE(pd.is_approved, FALSE)                  AS publisher_approved,
       COALESCE(pd.is_rejected, FALSE)                  AS publisher_rejected,
       LEAST(100, GREATEST(0,
            CASE WHEN COALESCE(cve.kev_count, 0) > 0 THEN 100 ELSE 0 END
          + COALESCE(cve.max_cvss_recent, cve.max_cvss, 0) * 10
          + COALESCE(cve.max_epss_recent, cve.max_epss, 0) * 40
          + LEAST(30, COALESCE(osint.threat_hits, 0) * 10 + COALESCE(pub_osint.pub_threat_hits, 0) * 5)
          + CASE WHEN COALESCE(td.is_rejected, FALSE)     THEN 50 ELSE 0 END
          + CASE WHEN COALESCE(pd.is_rejected, FALSE)     THEN 30 ELSE 0 END
          - CASE WHEN COALESCE(td.is_approved, FALSE)     THEN 100 ELSE 0 END
          - CASE WHEN COALESCE(pd.is_approved, FALSE)     THEN 100 ELSE 0 END
       ))::int AS safety_score,
       CASE
         -- Operator has explicitly approved (title or publisher) →
         -- respect that decision; the operator has accepted the risk.
         WHEN COALESCE(td.is_approved, FALSE)
              OR COALESCE(pd.is_approved, FALSE)                          THEN 'clean'
         -- Actively exploited beats everything else.
         WHEN COALESCE(cve.kev_count, 0) > 0                              THEN 'high'
         -- Severe CVE within the recency window.
         WHEN COALESCE(cve.max_cvss_recent, 0) >= 7.0                     THEN 'high'
         WHEN COALESCE(cve.max_cvss_recent, 0) >= 4.0                     THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) >= 3                         THEN 'medium'
         WHEN COALESCE(osint.threat_hits, 0) > 0
              OR COALESCE(pub_osint.pub_threat_hits, 0) > 0                THEN 'low'
         ELSE 'unknown'
       END AS safety_band
  FROM fleet_titles ft
  LEFT JOIN publisher_alias_resolved par
         ON par.tenant_id = ft.tenant_id AND par.canonical_name = ft.canonical_name
  LEFT JOIN per_title_cves     cve  ON cve.tenant_id = ft.tenant_id
                                    AND cve.canonical_name = ft.canonical_name
  LEFT JOIN per_title_osint    osint ON osint.tenant_id = ft.tenant_id
                                    AND LOWER(osint.canonical_name) = LOWER(ft.canonical_name)
  LEFT JOIN per_publisher_osint pub_osint ON pub_osint.tenant_id = ft.tenant_id
                                    AND pub_osint.publisher_lc = LOWER(COALESCE(par.resolved_publisher, ft.publisher, ''))
  LEFT JOIN title_decisions    td   ON td.tenant_id = ft.tenant_id
                                    AND td.canonical_lc = LOWER(ft.canonical_name)
  LEFT JOIN publisher_decisions pd  ON pd.tenant_id = ft.tenant_id
                                    AND pd.publisher_lc = LOWER(COALESCE(par.resolved_publisher, ft.publisher, ''));

CREATE UNIQUE INDEX IF NOT EXISTS v_software_safety_pk
    ON operations.v_software_safety (tenant_id, canonical_name);
CREATE INDEX IF NOT EXISTS v_software_safety_band_idx
    ON operations.v_software_safety (tenant_id, safety_band);
CREATE INDEX IF NOT EXISTS v_software_safety_publisher_idx
    ON operations.v_software_safety (tenant_id, LOWER(resolved_publisher));

GRANT SELECT ON operations.v_software_safety
   TO operations_app, operations_readonly, metabase_ro;
"""

REVERSE_SQL = """
DROP MATERIALIZED VIEW IF EXISTS operations.v_software_safety;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0087_seed_matcher_hints_and_publisher_rules"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
