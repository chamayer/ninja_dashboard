"""Migration 0040 — device_session_current matview (Track O batch O1).

Per DESIGN.md §3.8 (four-layer storage separation). Ops's first
device-grain derived matview: aggregates presence across all sources
from `agent_presence_current` and joins latest Ninja
`device_snapshots` for `needs_reboot` + `last_boot`. Powers the
findings-queue online-source map today, and the `reboot_pending`
finding coming in batch O5.

Design notes:

- One row per non-deleted device. Non-Ninja devices get the row with
  presence fields populated from any source that observes them, and
  NULL needs_reboot / last_boot_at (Ninja is the only reboot signal
  today).
- `is_online_any` and `online_sources` are computed at REFRESH time
  (24h contact window anchored to `NOW()` when the matview refreshes).
  With hourly refresh cadence this is at most 1h stale — acceptable
  vs the simpler consumer code. Move to query-time if precision
  matters later.
- Tenant scoping: matviews cannot have RLS enabled (Postgres
  limitation). Effective scoping comes through the join to
  `operations.devices` which does have RLS. Direct SELECT by a
  trusted role (`metabase_ro`) bypasses this — same shape as
  `agent_presence_current` today. Tracked for O5 tightening via a
  security-barrier view wrapper.
"""

from __future__ import annotations

from django.db import migrations


_VIEW_BODY = """
CREATE MATERIALIZED VIEW operations.device_session_current AS
WITH source_online AS (
    SELECT
        apc.device_id,
        apc.platform,
        apc.entity_type,
        apc.last_observed_at,
        apc.last_contact_at,
        apc.last_power_state,
        (
            (apc.entity_type LIKE 'agent.%%'
             AND COALESCE(apc.last_contact_at, apc.last_observed_at)
                 > NOW() - INTERVAL '24 hours')
            OR
            (apc.entity_type IN ('vm.guest', 'vm.host')
             AND apc.last_power_state = 'poweredon')
        ) AS is_online_now
    FROM operations.agent_presence_current apc
),
per_device_presence AS (
    SELECT
        so.device_id,
        MAX(so.last_contact_at)  AS last_contact_at,
        MAX(so.last_observed_at) AS last_observed_at,
        BOOL_OR(so.is_online_now) AS is_online_any,
        ARRAY_AGG(DISTINCT so.platform ORDER BY so.platform)
            FILTER (WHERE so.is_online_now)                AS online_sources,
        COUNT(DISTINCT so.platform)
            FILTER (WHERE so.is_online_now)                AS source_count_active,
        (ARRAY_AGG(so.last_power_state ORDER BY so.last_observed_at DESC)
            FILTER (WHERE so.entity_type = 'vm.guest'))[1] AS last_power_state
    FROM source_online so
    GROUP BY so.device_id
),
-- Latest snapshot per ninja device — DISTINCT ON works directly with
-- the (device_id, snapshot_at DESC) index on ninja_core.device_snapshots
-- (index-only skip scan). Join to device_links after, one row per Ninja
-- device, so the outer plan doesn't have to sort millions of snapshot
-- rows.
latest_ninja_snapshot AS (
    SELECT DISTINCT ON (ns.device_id)
        ns.device_id AS ninja_device_id,
        ns.needs_reboot,
        ns.last_boot
    FROM ninja_core.device_snapshots ns
    ORDER BY ns.device_id, ns.snapshot_at DESC
),
device_reboot AS (
    SELECT
        dl.device_id AS ops_device_id,
        lns.needs_reboot,
        lns.last_boot
    FROM operations.device_links dl
    JOIN operations.sources s
      ON s.id = dl.source_id AND s.name = 'Ninja'
    JOIN latest_ninja_snapshot lns
      ON lns.ninja_device_id = dl.external_id::int
)
SELECT
    d.tenant_id,
    d.client_id,
    d.id AS device_id,
    p.last_contact_at,
    p.last_observed_at,
    COALESCE(p.is_online_any, FALSE)               AS is_online_any,
    COALESCE(p.online_sources, ARRAY[]::text[])    AS online_sources,
    COALESCE(p.source_count_active, 0)             AS source_count_active,
    ls.needs_reboot,
    ls.last_boot                                    AS last_boot_at,
    p.last_power_state,
    NOW()                                           AS computed_at
FROM operations.devices d
LEFT JOIN per_device_presence p  ON p.device_id     = d.id
LEFT JOIN device_reboot        ls ON ls.ops_device_id = d.id
WHERE d.deleted_at IS NULL
WITH DATA;
"""


def upgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.device_session_current;"
    )
    schema_editor.execute(_VIEW_BODY)
    schema_editor.execute(
        """
        CREATE UNIQUE INDEX idx_device_session_current_pk
            ON operations.device_session_current (tenant_id, device_id);
        """
    )
    schema_editor.execute(
        """
        CREATE INDEX idx_device_session_current_online
            ON operations.device_session_current (tenant_id, is_online_any);
        """
    )
    schema_editor.execute(
        """
        CREATE INDEX idx_device_session_current_reboot
            ON operations.device_session_current (tenant_id, needs_reboot)
            WHERE needs_reboot;
        """
    )
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION operations.refresh_device_session_current()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY operations.device_session_current;
        END;
        $$;
        """
    )
    for role in ("operations_app", "ninja_ingest", "operations_readonly", "metabase_ro"):
        schema_editor.execute(
            f"GRANT SELECT ON operations.device_session_current TO {role};"
        )
    schema_editor.execute(
        "ALTER MATERIALIZED VIEW operations.device_session_current OWNER TO operations_migrate;"
    )
    schema_editor.execute(
        """
        GRANT EXECUTE ON FUNCTION operations.refresh_device_session_current()
            TO operations_app, ninja_ingest;
        """
    )
    # First refresh cannot use CONCURRENTLY (unique index just created).
    schema_editor.execute(
        "REFRESH MATERIALIZED VIEW operations.device_session_current;"
    )


def downgrade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS operations.refresh_device_session_current();"
    )
    schema_editor.execute(
        "DROP MATERIALIZED VIEW IF EXISTS operations.device_session_current;"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0039_patching_and_cutover_prep"),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
