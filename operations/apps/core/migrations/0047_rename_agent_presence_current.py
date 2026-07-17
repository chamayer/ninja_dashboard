"""Migration 0047 — rename agent_presence_current → device_agent_presence_current.

Standardization pass. The two later derived matviews land as
`device_session_current` and `device_patching_scope_current`
(pattern: `device_<layer>_current`). The oldest one predates the
convention. Rename brings all three onto the same shape so
future matviews follow the pattern by copy-paste.

Approach:
- ALTER MATERIALIZED VIEW ... RENAME TO — Postgres updates
  dependents by OID, so `device_session_current` and `v_device`
  keep working across the rename without a rebuild.
- Rename both indexes for consistency.
- Rebuild the refresh function under the new name (plpgsql body
  is a text literal; the old function's body would break at next
  call otherwise) and swap the refresh coordinator to call it.

No data loss — matview data is fully derived.

Follow-up (out of scope, tracked separately):
- Metabase questions that reference the old name will need updating.
"""

from __future__ import annotations

from django.db import migrations


_UPGRADE_SQL = """
-- 1. Rename the matview itself.
ALTER MATERIALIZED VIEW operations.agent_presence_current
    RENAME TO device_agent_presence_current;

-- 2. Rename its indexes to match the new base name.
ALTER INDEX operations.idx_agent_presence_pk
    RENAME TO idx_device_agent_presence_current_pk;
ALTER INDEX operations.idx_agent_presence_client
    RENAME TO idx_device_agent_presence_current_client;

-- 3. Rebuild the refresh function under the new name (plpgsql
--    body is literal SQL, so we can't rely on rename semantics
--    for the internal REFRESH statement).
DROP FUNCTION IF EXISTS operations.refresh_agent_presence_current();

CREATE OR REPLACE FUNCTION operations.refresh_device_agent_presence_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.device_agent_presence_current;
END;
$$;

GRANT EXECUTE ON FUNCTION operations.refresh_device_agent_presence_current()
    TO operations_app, ninja_ingest;

-- 4. Swap the coordinator over to the new function name.
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_device_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
END;
$$;
"""


_REVERSE_SQL = """
CREATE OR REPLACE FUNCTION operations.refresh_derived()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM operations.refresh_agent_presence_current();
    PERFORM operations.refresh_device_session_current();
    PERFORM operations.refresh_patching_scope_current();
END;
$$;

DROP FUNCTION IF EXISTS operations.refresh_device_agent_presence_current();

CREATE OR REPLACE FUNCTION operations.refresh_agent_presence_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.agent_presence_current;
END;
$$;

GRANT EXECUTE ON FUNCTION operations.refresh_agent_presence_current()
    TO operations_app, ninja_ingest;

ALTER INDEX operations.idx_device_agent_presence_current_client
    RENAME TO idx_agent_presence_client;
ALTER INDEX operations.idx_device_agent_presence_current_pk
    RENAME TO idx_agent_presence_pk;

ALTER MATERIALIZED VIEW operations.device_agent_presence_current
    RENAME TO agent_presence_current;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0046_evaluator_config"),
    ]

    operations = [
        migrations.RunSQL(_UPGRADE_SQL, reverse_sql=_REVERSE_SQL),
    ]
