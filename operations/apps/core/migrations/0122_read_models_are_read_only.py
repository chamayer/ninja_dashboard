"""Migration 0122 — read models grant SELECT only.

Every view and materialized view in the ``operations`` schema had been granting
``INSERT``, ``UPDATE`` and ``DELETE`` to ``operations_app``. None of it was
deliberate. ``ALTER DEFAULT PRIVILEGES ... IN SCHEMA operations`` grants
``operations_app=arwd`` on relations created by ``operations_migrate``, and
PostgreSQL's default-privilege object type ``r`` covers views and materialized
views as well as tables. So every read model created by a migration silently
inherited write privileges, regardless of what that migration granted
explicitly. Migration 0121 granted ``v_device_source_link`` SELECT only and it
still came out with all four.

Seventeen relations were affected. For most the grant was inert: PostgreSQL
does not accept DML against a materialized view at all, and a view is only
auto-updatable if it draws from a single base table without aggregation, so
``v_device``, ``v_device_source_link``, ``v_entity_attribute_claim_current``
and the rest reject writes on their shape regardless of privilege.

Three were auto-updatable, and one of those was a real privilege escalation.
Measured against production before this migration, as ``operations_app``:

* ``entity_attribute_claim_current`` and ``entity_attribute_claim_history``
  are denied directly — ``permission denied for table`` — as migration 0115
  and 0117 intended. But ``DELETE`` through
  ``v_entity_attribute_claim_storage_status`` **succeeded**. That view is
  ``security_barrier``, not ``security_invoker``, so DML through it is
  permission-checked as its owner ``operations_migrate``, a superuser. The
  view handed the application write access to two tables the E5.2 privilege
  cutover had explicitly taken away.
* ``ninja_device_detail_current_shadow`` and
  ``ninja_device_health_current_shadow`` also accepted writes, but these are
  ``security_invoker``, so the check ran as ``operations_app`` against
  ``entity_observation_current``, where it already holds
  ``INSERT``/``UPDATE``/``DELETE`` directly and legitimately (device merge
  repoints observations). No escalation, but no reason to write through a
  read model either.

No application code writes through any of these — verified by searching for
DML against every affected relation name.

This migration revokes ``INSERT``, ``UPDATE``, ``DELETE`` and ``TRUNCATE`` from
the four runtime roles on every view and materialized view in the schema, then
asserts that none remains, so a missed relation fails the migration rather than
passing quietly. ``SELECT`` is untouched.

**The default privilege is not changed, and cannot be narrowed.** PostgreSQL
has no default-privilege object type that distinguishes a view from a table, so
tables must keep ``arwd`` for the application to function. The rule is
therefore stated in ``operations/AGENTS.md``: a migration creating a read model
must revoke the DML it inherits. This migration's assertion catches the current
population only; anything created after it is on the next author. A continuous
check is recorded in ``.work/backlog.md``.
"""

from typing import ClassVar

from django.db import migrations

RUNTIME_ROLES = "operations_app, operations_readonly, metabase_ro, ninja_ingest"

FORWARD_SQL = f"""
DO $block$
DECLARE
    rec record;
BEGIN
    FOR rec IN
        SELECT c.relname
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'operations'
           AND c.relkind IN ('v', 'm')
         ORDER BY c.relname
    LOOP
        EXECUTE format(
            'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.%I FROM {RUNTIME_ROLES}',
            rec.relname
        );
    END LOOP;
END
$block$;

DO $block$
DECLARE
    v_offenders text;
BEGIN
    SELECT string_agg(DISTINCT c.relname || ' -> ' || pg_get_userbyid(a.grantee),
                      ', ' ORDER BY c.relname || ' -> ' || pg_get_userbyid(a.grantee))
      INTO v_offenders
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      CROSS JOIN LATERAL aclexplode(c.relacl) a
     WHERE n.nspname = 'operations'
       AND c.relkind IN ('v', 'm')
       AND pg_get_userbyid(a.grantee) IN
           ('operations_app', 'operations_readonly', 'metabase_ro', 'ninja_ingest')
       AND a.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE');

    IF v_offenders IS NOT NULL THEN
        RAISE EXCEPTION
            'read models still grant write privileges to runtime roles: %',
            v_offenders;
    END IF;

    RAISE NOTICE 'all operations read models grant SELECT only to runtime roles';
END
$block$;
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0121_retire_device_links"),
    ]

    # Deliberately irreversible. Reversing would re-grant write privileges that
    # were never intended and that one view turned into a privilege escalation.
    operations: ClassVar = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
