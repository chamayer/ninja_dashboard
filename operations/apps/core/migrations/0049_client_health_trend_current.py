"""Migration 0049 — client_health_trend_current matview.

Fourth derived matview in the `<subject>_<layer>_current` family.
Computes each client's open-issue counts (severe + total) as of
NOW, 7 days ago, and 30 days ago, from the newly-clean timestamps
introduced in migration 0048.

Reads:
  - operations.findings (first_seen_at + closed_at + severity)
  - operations.clients (client list)

Refresh: `operations.refresh_client_health_trend_current()`,
called by the `refresh_derived()` coordinator after the other
three matviews.

Wave UI-2 follow-up (G2.2).
"""

from __future__ import annotations

from django.db import migrations


_VIEW_BODY = """
CREATE MATERIALIZED VIEW operations.client_health_trend_current AS
SELECT
    c.tenant_id,
    c.id AS client_id,

    -- open now
    COUNT(*) FILTER (
        WHERE f.closed_at IS NULL
          AND f.severity IN ('critical', 'high')
    )::int AS severe_open_now,
    COUNT(*) FILTER (
        WHERE f.closed_at IS NULL
    )::int AS open_now,

    -- open as-of 7 days ago
    COUNT(*) FILTER (
        WHERE f.first_seen_at <= NOW() - INTERVAL '7 days'
          AND (f.closed_at IS NULL OR f.closed_at > NOW() - INTERVAL '7 days')
          AND f.severity IN ('critical', 'high')
    )::int AS severe_open_7d_ago,
    COUNT(*) FILTER (
        WHERE f.first_seen_at <= NOW() - INTERVAL '7 days'
          AND (f.closed_at IS NULL OR f.closed_at > NOW() - INTERVAL '7 days')
    )::int AS open_7d_ago,

    -- open as-of 30 days ago
    COUNT(*) FILTER (
        WHERE f.first_seen_at <= NOW() - INTERVAL '30 days'
          AND (f.closed_at IS NULL OR f.closed_at > NOW() - INTERVAL '30 days')
          AND f.severity IN ('critical', 'high')
    )::int AS severe_open_30d_ago,

    NOW() AS computed_at
FROM operations.clients c
LEFT JOIN operations.findings f
       ON f.tenant_id = c.tenant_id
      AND f.client_id = c.id
WHERE c.deleted_at IS NULL
GROUP BY c.tenant_id, c.id
WITH DATA;
"""


_REFRESH_FN = """
CREATE OR REPLACE FUNCTION operations.refresh_client_health_trend_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.client_health_trend_current;
END;
$$;

GRANT EXECUTE ON FUNCTION operations.refresh_client_health_trend_current()
    TO operations_app, ninja_ingest;
"""


_COORDINATOR = """
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_device_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
    PERFORM operations.refresh_client_health_trend_current();
END;
$$;
"""


_UPGRADE_SQL = _VIEW_BODY + """
CREATE UNIQUE INDEX idx_client_health_trend_current_pk
    ON operations.client_health_trend_current (tenant_id, client_id);
GRANT SELECT ON operations.client_health_trend_current TO operations_app, ninja_ingest;
ALTER MATERIALIZED VIEW operations.client_health_trend_current OWNER TO operations_migrate;
""" + _REFRESH_FN + _COORDINATOR


_REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_device_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
END;
$$;

DROP FUNCTION IF EXISTS operations.refresh_client_health_trend_current();
DROP MATERIALIZED VIEW IF EXISTS operations.client_health_trend_current;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0048_finding_acknowledged_and_closed"),
    ]

    operations = [
        migrations.RunSQL(_UPGRADE_SQL, reverse_sql=_REVERSE_SQL),
    ]
