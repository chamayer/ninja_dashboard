"""Restore app read access to the Ninja device shadow views.

Migration 0117 revoked table-level ``SELECT`` on
``operations.entity_observation_current`` from ``operations_app``,
``operations_readonly`` and ``metabase_ro``, leaving only column-level
``SELECT (observation_id)``. The observation payload is restricted evidence and
full reads go through the audited ``reveal_entity_observation`` function.

``ninja_device_detail_current_shadow`` and ``ninja_device_health_current_shadow``
project a handful of scalars out of ``canonical_data``, and both are
``security_invoker``, so their permission check runs as the *calling* role.
After 0117 that role could no longer read the table, and every query against
either view has failed with ``permission denied for table
entity_observation_current`` ever since. ``/software/user-risk/`` returns HTTP
500 on every request as a result — in 26 ms, which is why no timing-based
check ever noticed. Measured 2026-08-17.

Migration 0122 inspected both views, recorded that they are ``security_invoker``
and that the app holds INSERT/UPDATE/DELETE on the underlying table, and did
not notice that the SELECT those views depend on had been taken away.

The fix is the pattern 0117 established for itself: a ``security_barrier`` view
owned by ``operations_view_owner``, which holds the table ``SELECT``. That is
exactly how ``v_entity_observation_admin_metadata`` exposes
``canonical_data->>'hostname'`` and ``->>'platform_group_id'`` today. The app
sees only what the view projects; the payload stays out of reach.

Deliberately **not** applied to ``ninja_device_seen_daily_shadow``. It reads
``operations.source_record_seen_daily``, where ``operations_app`` has SELECT and
``operations_view_owner`` does not, so re-owning it would break a view that
works today. Verified 2026-08-17.

Rehearsed against production in a rolled-back transaction: both views return
5,557 rows to ``operations_app``; tenant 999 sees 0, so RLS ``tenant_isolation``
still applies (the policy targets PUBLIC, and the new owner is not the table
owner); a direct ``canonical_data`` read and a read of an unprojected key both
still fail with permission denied.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER VIEW operations.ninja_device_detail_current_shadow
    SET (security_barrier = true, security_invoker = false);
ALTER VIEW operations.ninja_device_detail_current_shadow
    OWNER TO operations_view_owner;

ALTER VIEW operations.ninja_device_health_current_shadow
    SET (security_barrier = true, security_invoker = false);
ALTER VIEW operations.ninja_device_health_current_shadow
    OWNER TO operations_view_owner;

-- 0122's rule: a read model must not accept writes. The owner change makes DML
-- through these views run as operations_view_owner, so restate the revoke
-- rather than rely on it having been done while they were invoker views.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    operations.ninja_device_detail_current_shadow,
    operations.ninja_device_health_current_shadow
FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;

GRANT SELECT ON
    operations.ninja_device_detail_current_shadow,
    operations.ninja_device_health_current_shadow
TO operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""

REVERSE_SQL = r"""
ALTER VIEW operations.ninja_device_detail_current_shadow
    SET (security_invoker = true, security_barrier = false);
ALTER VIEW operations.ninja_device_detail_current_shadow
    OWNER TO operations_migrate;

ALTER VIEW operations.ninja_device_health_current_shadow
    SET (security_invoker = true, security_barrier = false);
ALTER VIEW operations.ninja_device_health_current_shadow
    OWNER TO operations_migrate;
"""


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0141_identity_serial_quality"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
