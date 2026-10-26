"""Rename a client, by an operator or because its sources renamed it.

A source group id that reports a new name is a rename (user, 2026-10-26).
``operations.rename_client_v1`` is the one recorded change for both: it sets
the display name, keeps the old name as an alias so groups still reporting it
keep matching, and leaves the slug (saved links) unchanged. The resolver calls
it with no actor when every mapped group agrees on the new name; the client
page calls it for an operator, including to undo an automatic rename. The
change action ``client.rename`` carries the old and new names, which the
client page reads for Undo.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION operations.rename_client_v1(
    p_tenant_id bigint,
    p_client_id uuid,
    p_new_name text,
    p_reason text,
    p_actor_id bigint
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    v_old text;
    v_new text := btrim(coalesce(p_new_name, ''));
    v_old_norm text;
    v_new_norm text;
    v_reason text := btrim(coalesce(p_reason, ''));
BEGIN
    IF p_tenant_id <> 1 OR length(v_reason) NOT BETWEEN 1 AND 400
       OR length(v_new) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'rename_client: a name and a reason are required';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, true);
    SELECT display_name INTO v_old FROM operations.clients
     WHERE tenant_id = p_tenant_id AND id = p_client_id AND deleted_at IS NULL
       FOR UPDATE;
    IF v_old IS NULL THEN
        RAISE EXCEPTION 'rename_client: unknown or deleted client';
    END IF;
    IF v_old = v_new THEN
        RAISE EXCEPTION 'rename_client: the client already has that name';
    END IF;
    -- The resolver's name comparison (client_resolver._norm).
    v_old_norm := lower(regexp_replace(v_old, '[\s\-_.]', '', 'g'));
    v_new_norm := lower(regexp_replace(v_new, '[\s\-_.]', '', 'g'));
    IF EXISTS (SELECT 1 FROM operations.clients
                WHERE tenant_id = p_tenant_id AND id <> p_client_id AND deleted_at IS NULL
                  AND lower(regexp_replace(display_name, '[\s\-_.]', '', 'g')) = v_new_norm)
       OR EXISTS (SELECT 1 FROM operations.client_name_aliases
                   WHERE tenant_id = p_tenant_id AND client_id <> p_client_id
                     AND normalized_name = v_new_norm) THEN
        RAISE EXCEPTION 'rename_client: another client already uses that name';
    END IF;
    PERFORM operations.begin_change(
        'client.rename', v_reason,
        jsonb_build_object('client_id', p_client_id, 'from', v_old, 'to', v_new),
        CASE WHEN p_actor_id IS NULL THEN 'process' ELSE 'operator' END, p_actor_id,
        CASE WHEN p_actor_id IS NULL THEN 'ingest.identity.client_resolver'
             ELSE 'operations.ui' END,
        '', p_tenant_id, true);

    -- Groups still reporting the old name keep matching this client.
    IF v_old_norm <> '' AND v_old_norm <> v_new_norm THEN
        INSERT INTO operations.client_name_aliases (
            id, tenant_id, version, client_id, alias, normalized_name, tier, enabled,
            created_at, created_by, created_reason)
        VALUES (gen_random_uuid(), p_tenant_id, 1, p_client_id, v_old, v_old_norm,
                'manual', true, now(),
                CASE WHEN p_actor_id IS NULL THEN 'resolver' ELSE 'operator' END,
                left('Former name (renamed to ' || v_new || ')', 120))
        ON CONFLICT (tenant_id, normalized_name) DO NOTHING;
    END IF;

    UPDATE operations.clients
       SET display_name = v_new, updated_at = now(), updated_reason = 'client.rename'
     WHERE id = p_client_id;
    RETURN v_old;
END
$fn$;

REVOKE ALL ON FUNCTION operations.rename_client_v1(bigint, uuid, text, text, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.rename_client_v1(bigint, uuid, text, text, bigint)
    TO ninja_ingest, operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0346_restricted_layouts_join_once"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
