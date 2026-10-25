"""Automatic client promotion (ADR-0041).

* ``clients.provisional_since`` / ``provisional_reason``: a client the resolver
  created on evidence; ``verified_at`` / ``verified_by`` record when an
  operator confirmed it. Track C stands: a source is never the authority, the
  client is a recorded, changeable suggestion until verified.
* ``operations.promote_client_candidate_v1``: one recorded change that maps an
  open candidate to an existing client, or creates a provisional client for
  it (entity anchor, client, as Accept does), adds the source-tier alias the
  resolver then matches, and closes the candidate as decided by the resolver
  with the evidence as its reason. The resolver's name match attaches the
  groups in the same run, and their links get ``automatic``/``resolver``
  decisions carrying the alias reason (ADR-0040).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION operations.promote_client_candidate_v1(
    p_tenant_id bigint,
    p_candidate_id uuid,
    p_client_id uuid,
    p_reason text
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $fn$
DECLARE
    c operations.client_candidates%ROWTYPE;
    v_client uuid := p_client_id;
    v_name text;
    v_slug text;
    v_base text;
    v_suffix integer := 1;
    v_reason text := left(btrim(coalesce(p_reason, '')), 120);
BEGIN
    IF p_tenant_id <> 1 OR v_reason = '' THEN
        RAISE EXCEPTION 'promote_client_candidate: a reason is required';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, true);
    SELECT * INTO c FROM operations.client_candidates
     WHERE tenant_id = p_tenant_id AND id = p_candidate_id FOR UPDATE;
    IF c.id IS NULL OR c.status <> 'open' THEN
        RAISE EXCEPTION 'promote_client_candidate: the candidate is not open';
    END IF;
    IF EXISTS (SELECT 1 FROM operations.client_name_aliases
                WHERE tenant_id = p_tenant_id AND normalized_name = c.normalized_name) THEN
        RAISE EXCEPTION 'promote_client_candidate: the name already has an alias';
    END IF;
    PERFORM operations.begin_change(
        'client.promote', v_reason,
        jsonb_build_object('candidate_id', c.id, 'client_id', p_client_id),
        'process', NULL, 'ingest.identity.client_resolver', '', p_tenant_id, true);

    IF v_client IS NULL THEN
        v_name := coalesce(nullif(btrim(c.display_name), ''), c.normalized_name);
        v_base := left(coalesce(nullif(trim(BOTH '-' FROM regexp_replace(
                      lower(v_name), '[^a-z0-9]+', '-', 'g')), ''), 'client'), 110);
        v_slug := v_base;
        WHILE EXISTS (SELECT 1 FROM operations.clients
                       WHERE tenant_id = p_tenant_id AND slug = v_slug) LOOP
            v_suffix := v_suffix + 1;
            v_slug := v_base || '-' || v_suffix;
        END LOOP;
        v_client := gen_random_uuid();
        -- A client is anchored by a tenant entity sharing its id (ADR-0012, 0120).
        INSERT INTO operations.entities (
            id, tenant_id, entity_class_id, scope_kind, client_id, version, created_at,
            created_reason, updated_at, updated_reason, retired_at, retired_reason,
            deleted_at, deleted_reason)
        VALUES (v_client, p_tenant_id, 'client', 'tenant', NULL, 1, now(),
                'resolver.promote', now(), 'resolver.promote', NULL, '', NULL, '');
        INSERT INTO operations.clients (
            id, tenant_id, version, entity_id, slug, display_name, timezone,
            offline_after_days, requirement_profile_id, created_at, created_reason,
            updated_at, updated_reason, stale_since, stale_reason, deleted_at,
            deleted_reason, provisional_since, provisional_reason, verified_at, verified_by)
        VALUES (v_client, p_tenant_id, 1, v_client, v_slug, v_name, 'UTC', NULL, NULL, now(),
                'resolver.promote', now(), 'resolver.promote', NULL, '', NULL, '',
                now(), v_reason, NULL, '');
    ELSIF NOT EXISTS (SELECT 1 FROM operations.clients
                       WHERE tenant_id = p_tenant_id AND id = v_client AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'promote_client_candidate: unknown or deleted client';
    END IF;

    INSERT INTO operations.client_name_aliases (
        id, tenant_id, version, client_id, alias, normalized_name, tier, enabled,
        created_at, created_by, created_reason)
    VALUES (gen_random_uuid(), p_tenant_id, 1, v_client,
            coalesce(nullif(btrim(c.display_name), ''), c.normalized_name),
            c.normalized_name, 'source', true, now(), 'resolver', v_reason);

    UPDATE operations.client_candidates
       SET status = CASE WHEN p_client_id IS NULL THEN 'accepted' ELSE 'mapped' END,
           resolved_client_id = v_client, resolved_at = now(),
           resolved_by = 'resolver', resolved_reason = left(v_reason, 240)
     WHERE id = c.id;
    RETURN v_client;
END
$fn$;

-- Admin-managed thresholds (ADR-0041); the resolver falls back to these keys'
-- code defaults, and creates nothing without a required source configured.
SELECT operations.begin_change(
    'client_promotion.register', 'ADR-0041: automatic client promotion settings.',
    '{"migration": "0342_automatic_client_promotion"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0342', 1, true);
INSERT INTO operations.evaluator_config (id, tenant_id, evaluator_name, config, updated_at)
VALUES (gen_random_uuid(), 1, 'client_promotion',
        '{"map_enabled": true, "map_min_names": 2, "create_enabled": true,
          "create_min_sources": 2, "create_required_source": "Ninja", "min_seen_runs": 2}'::jsonb,
        now())
ON CONFLICT (tenant_id, evaluator_name) DO NOTHING;

REVOKE ALL ON FUNCTION operations.promote_client_candidate_v1(bigint, uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.promote_client_candidate_v1(bigint, uuid, uuid, text)
    TO ninja_ingest;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0341_client_source_group_move"),
    ]

    operations: ClassVar[list] = [
        migrations.AddField(
            model_name="client",
            name="provisional_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="provisional_reason",
            field=models.CharField(blank=True, default="", max_length=240),
        ),
        migrations.AddField(
            model_name="client",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="verified_by",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
