"""Migration 0121 — retire ``operations.device_links`` (E6).

``device_links`` was the "competing attachment authority" E6 names. Six code
paths wrote it: ``resolver._attach_observation``, the two promotion INSERTs,
``fast_path._upsert_link_for_fast_match``,
``core.devices._sync_operations_device_links``, and ``views._merge_devices``.
The fifth filtered ``WHERE s.name = 'Ninja'``, so its two freshness columns
were only ever maintained for one of four sources.

Measured against production before this change:

* ``missing_since`` was wrong on 209 links — SentinelOne 137, LogMeIn 65,
  ScreenConnect 7, Ninja 0 — matching the Ninja-only filter exactly. Those
  links reported an agent present that had stopped reporting 6-23 days
  earlier, and ``evaluator`` resolves ``device_missing_from_source`` from that
  column, so the finding could not resolve for three of four sources.
* ``last_seen_at`` was frozen far more widely: it disagreed with the
  observation-derived value on 3,026/3,031 LogMeIn, 1,013/1,013 ScreenConnect
  and 4,346/4,351 SentinelOne links, against 0/5,884 Ninja. 8,316 links
  claimed present with ``last_seen_at`` at least three days stale.

The table is replaced by ``operations.v_device_source_link``, a thin read
surface over ``operations.entity_source_links`` — the table
``operations.sync_entity_source_links_from_observations()`` maintains from
observation evidence for every source. Attachment authority therefore moves to
observations, which is the ADR-0012 rule: a source assertion is evidence, and
no evidence producer writes canonical state directly.

Every reader is repointed to the new name in the same release; no
compatibility alias for ``device_links`` is left behind. A shim was written
first and rejected on three counts. It had to emit ``match_method``,
``match_confidence`` and ``external_name`` as constants because the shim
collapsed the rows that carry them — inventing values no reader consumed. It
needed a synthetic primary key, since the natural one belonged to the member
rows. And it was catastrophically slow, below.

**Why this view has no aggregate.** ``entity_source_links`` records one row per
external namespace, and the obvious reading is that the namespaces must be
collapsed per ``(tenant, source, external_id)``. They must not. Ninja is the
only source with two namespaces, ``device`` and ``device-health``, and
``device-health`` is the health-poll companion of the same records — the same
five entity types, already excluded from device presence by migration 0098.
Excluding it yields exactly one row per key with no grouping at all. Verified
against production: the flat and aggregated forms produce identical row sets
(14,286 each, zero rows on either side of the difference), zero duplicate
keys, and — compared row by row — zero disagreement on ``missing_since``
presence and zero on ``last_seen_at``.

That is not a micro-optimization. Building
``device_patching_scope_current`` measured 247 ms against the original
``device_links`` table, more than 90 s (statement timeout) through the
aggregating shim, and 278 ms through this flat view. The aggregate form is a
~365x regression that would have taken the patching dashboard down, and it
planned identically to the fast form — same nodes, same cost estimate — so
only execution against production revealed it.

The matview is rewritten here rather than captured and restored, because its
``ninja_linked`` CTE is the part that changes. ``v_device`` reads the matview
and is unchanged, so it is captured from the live catalog and restored
verbatim: transcribe what changes, preserve what does not.

Both new relations are ``security_invoker = true``, matching ``v_device``.
That is load-bearing, not stylistic: ingest connects as ``ninja``, which is
BYPASSRLS, and refreshes the matview with no ``operations.tenant_id`` GUC set.
A default view would evaluate RLS as its own owner, lose that BYPASSRLS, match
the tenant policy against a NULL GUC and return zero rows. ``security_invoker``
reproduces the retired table's semantics exactly.

The migration asserts parity before it destroys anything: it builds the new
matview contents and compares them row for row against the deployed matview,
raising if any ``(device_id, scope_derived, scope_reason)`` differs.

Not reversible. The retired table's ``match_method``, ``match_confidence`` and
``external_name`` values are not reconstructible; nothing read them.
"""

from typing import ClassVar

from django.db import migrations, models

CREATE_VIEW_SQL = r"""
CREATE VIEW operations.v_device_source_link
WITH (security_invoker = true) AS
SELECT link.id,
       link.tenant_id,
       link.entity_id                  AS device_id,
       instance.source_id,
       link.external_id::varchar(240)  AS external_id,
       link.external_namespace,
       link.first_seen_at,
       link.last_seen_at,
       link.missing_since,
       link.match_method,
       link.match_confidence
FROM operations.entity_source_links link
JOIN operations.source_instances instance
  ON instance.id = link.source_instance_id
WHERE link.entity_class_id = 'device'
  -- 'asset' is Hudu CMDB evidence, which was never a device link.
  -- 'device-health' is Ninja's health-poll companion namespace covering the
  -- same records; excluding it leaves exactly one row per
  -- (tenant, source, external_id) and so needs no aggregation. See the module
  -- docstring for the production verification of that equivalence.
  AND link.external_namespace NOT IN ('asset', 'device-health');

ALTER VIEW operations.v_device_source_link OWNER TO operations_migrate;

GRANT SELECT ON operations.v_device_source_link
    TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

-- security_invoker resolves the underlying relations as the caller, so the
-- ingest role needs read access to the relations this view joins.
GRANT SELECT ON operations.source_instances, operations.sources TO ninja_ingest;
"""


# Fails the migration if the rewritten matview would change any device's
# patching scope. Runs before anything is dropped.
PARITY_SQL = r"""
CREATE TEMP TABLE _dpsc_new AS
WITH ninja_linked AS (
         SELECT DISTINCT ON (d_1.id) d_1.tenant_id,
            d_1.id AS device_id,
            d_1.device_role,
            d_1.os_group,
            nd.id AS ninja_device_id,
            nd.organization_id,
            nd.location_id,
            COALESCE(pol.name, rpol.name) AS effective_policy_name
           FROM operations.devices d_1
             JOIN operations.v_device_source_link dl ON dl.device_id = d_1.id AND dl.tenant_id = d_1.tenant_id
             JOIN operations.sources s ON s.id = dl.source_id AND s.name::text = 'Ninja'::text
             JOIN ninja_core.devices nd ON nd.id::text = dl.external_id::text
             LEFT JOIN ninja_core.policies pol ON pol.id = nd.policy_id
             LEFT JOIN ninja_core.policies rpol ON rpol.id = nd.role_policy_id
          WHERE d_1.deleted_at IS NULL
          ORDER BY d_1.id, dl.last_seen_at DESC NULLS LAST
        ), device_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'DEVICE'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'patchingEnabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), organization_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'ORGANIZATION'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), location_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'LOCATION'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), signals AS (
         SELECT nl_1.tenant_id,
            nl_1.device_id,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'patchingDisabled'::text) AS d_disabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'patchingEnabled'::text) AS d_enabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'workstationPatchingDisabled'::text) AS d_ws_disabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'serverPatchingDisabled'::text) AS d_sv_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'patchingDisabled'::text) AS o_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'workstationPatchingDisabled'::text) AS o_ws_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'serverPatchingDisabled'::text) AS o_sv_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'patchingDisabled'::text) AS l_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'workstationPatchingDisabled'::text) AS l_ws_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'serverPatchingDisabled'::text) AS l_sv_disabled,
            max(nl_1.effective_policy_name) AS effective_policy_name
           FROM ninja_linked nl_1
             LEFT JOIN device_cf dcf ON dcf.entity_id = nl_1.ninja_device_id
             LEFT JOIN organization_cf ocf ON ocf.entity_id = nl_1.organization_id
             LEFT JOIN location_cf lcf ON lcf.entity_id = nl_1.location_id
          GROUP BY nl_1.tenant_id, nl_1.device_id
        )
 SELECT d.tenant_id,
    d.id AS device_id,
    d.device_role,
        CASE
            WHEN nl.ninja_device_id IS NULL THEN 'Unmanaged'::character varying
            WHEN d.os_group::text <> 'Windows'::text THEN 'Unmanaged'::character varying
            WHEN COALESCE(sig.d_disabled, sig.o_disabled, sig.l_disabled, false) THEN 'Excluded'::character varying
            WHEN COALESCE(sig.d_enabled, false) THEN 'Included'::character varying
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.d_ws_disabled, sig.o_ws_disabled, sig.l_ws_disabled, false) THEN 'Excluded'::character varying
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.d_sv_disabled, sig.o_sv_disabled, sig.l_sv_disabled, false) THEN 'Excluded'::character varying
            WHEN d.device_role::text = 'server'::text AND sig.effective_policy_name IS NOT NULL AND (EXISTS ( SELECT 1
               FROM operations.patching_scope_policy_allowlist a
              WHERE a.enabled AND a.policy_name::text = sig.effective_policy_name)) THEN 'Included'::character varying
            ELSE COALESCE(( SELECT def.effect
               FROM operations.patching_scope_default def
              WHERE def.device_role::text = d.device_role::text AND def.enabled), 'Unmanaged'::character varying)
        END AS scope_derived,
        CASE
            WHEN nl.ninja_device_id IS NULL THEN 'no-ninja-link'::text
            WHEN d.os_group::text <> 'Windows'::text THEN 'os-group-not-windows'::text
            WHEN COALESCE(sig.d_disabled, false) THEN 'device.patchingDisabled'::text
            WHEN COALESCE(sig.o_disabled, false) THEN 'organization.patchingDisabled'::text
            WHEN COALESCE(sig.l_disabled, false) THEN 'location.patchingDisabled'::text
            WHEN COALESCE(sig.d_enabled, false) THEN 'device.patchingEnabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.d_ws_disabled, false) THEN 'device.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.o_ws_disabled, false) THEN 'organization.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.l_ws_disabled, false) THEN 'location.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.d_sv_disabled, false) THEN 'device.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.o_sv_disabled, false) THEN 'organization.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.l_sv_disabled, false) THEN 'location.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND sig.effective_policy_name IS NOT NULL AND (EXISTS ( SELECT 1
               FROM operations.patching_scope_policy_allowlist a
              WHERE a.enabled AND a.policy_name::text = sig.effective_policy_name)) THEN 'policy-allowlist:'::text || sig.effective_policy_name
            ELSE 'default:'::text || COALESCE(NULLIF(d.device_role::text, ''::text), 'unknown'::text)
        END AS scope_reason,
    now() AS computed_at
   FROM operations.devices d
     LEFT JOIN ninja_linked nl ON nl.device_id = d.id AND nl.tenant_id = d.tenant_id
     LEFT JOIN signals sig ON sig.device_id = d.id AND sig.tenant_id = d.tenant_id
  WHERE d.deleted_at IS NULL;

DO $block$
DECLARE
    v_new  bigint;
    v_diff bigint;
BEGIN
    SELECT count(*) INTO v_new FROM _dpsc_new;

    SELECT count(*) INTO v_diff FROM (
        (SELECT device_id, scope_derived, scope_reason
           FROM operations.device_patching_scope_current
         EXCEPT
         SELECT device_id, scope_derived, scope_reason FROM _dpsc_new)
        UNION ALL
        (SELECT device_id, scope_derived, scope_reason FROM _dpsc_new
         EXCEPT
         SELECT device_id, scope_derived, scope_reason
           FROM operations.device_patching_scope_current)
    ) d;

    IF v_diff <> 0 THEN
        RAISE EXCEPTION
            'device_patching_scope_current parity failed: % rows differ; '
            'refusing to retire device_links', v_diff;
    END IF;

    RAISE NOTICE 'patching scope parity verified: % rows, 0 differences', v_new;
END
$block$;

DROP TABLE _dpsc_new;
"""


# v_device is not being changed, only rebuilt, so it is preserved verbatim from
# the live catalog rather than transcribed.
CAPTURE_SQL = r"""
CREATE TEMP TABLE _vdev_stash AS
SELECT rtrim(btrim(pg_get_viewdef(cls.oid, true)), ';') AS viewdef,
       pg_get_userbyid(cls.relowner)                    AS owner,
       cls.reloptions                                   AS reloptions,
       (SELECT array_agg(format('GRANT %s ON operations.v_device TO %I',
                                acl.privilege_type,
                                pg_get_userbyid(acl.grantee)))
          FROM aclexplode(cls.relacl) acl
         WHERE acl.grantee <> 0 AND acl.grantee <> cls.relowner) AS grants
  FROM pg_class cls
  JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
 WHERE nsp.nspname = 'operations' AND cls.relname = 'v_device';

DO $block$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM _vdev_stash WHERE viewdef IS NOT NULL AND viewdef <> ''
    ) THEN
        RAISE EXCEPTION 'could not capture operations.v_device; refusing to proceed';
    END IF;
END
$block$;
"""


REPLACE_SQL = r"""
-- Dropped in dependency order rather than with CASCADE, so an unexpected extra
-- dependent fails the migration instead of being silently destroyed.
DROP VIEW operations.v_device;
DROP MATERIALIZED VIEW operations.device_patching_scope_current;
DROP TABLE operations.device_links;

CREATE MATERIALIZED VIEW operations.device_patching_scope_current AS
WITH ninja_linked AS (
         SELECT DISTINCT ON (d_1.id) d_1.tenant_id,
            d_1.id AS device_id,
            d_1.device_role,
            d_1.os_group,
            nd.id AS ninja_device_id,
            nd.organization_id,
            nd.location_id,
            COALESCE(pol.name, rpol.name) AS effective_policy_name
           FROM operations.devices d_1
             JOIN operations.v_device_source_link dl ON dl.device_id = d_1.id AND dl.tenant_id = d_1.tenant_id
             JOIN operations.sources s ON s.id = dl.source_id AND s.name::text = 'Ninja'::text
             JOIN ninja_core.devices nd ON nd.id::text = dl.external_id::text
             LEFT JOIN ninja_core.policies pol ON pol.id = nd.policy_id
             LEFT JOIN ninja_core.policies rpol ON rpol.id = nd.role_policy_id
          WHERE d_1.deleted_at IS NULL
          ORDER BY d_1.id, dl.last_seen_at DESC NULLS LAST
        ), device_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'DEVICE'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'patchingEnabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), organization_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'ORGANIZATION'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), location_cf AS (
         SELECT DISTINCT ON (custom_field_values.entity_id, custom_field_values.field_name) custom_field_values.entity_id,
            custom_field_values.field_name,
            custom_field_values.value_bool
           FROM ninja_core.custom_field_values
          WHERE custom_field_values.entity_type = 'LOCATION'::text AND (custom_field_values.field_name = ANY (ARRAY['patchingDisabled'::text, 'serverPatchingDisabled'::text, 'workstationPatchingDisabled'::text]))
          ORDER BY custom_field_values.entity_id, custom_field_values.field_name, custom_field_values.last_observed_at DESC
        ), signals AS (
         SELECT nl_1.tenant_id,
            nl_1.device_id,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'patchingDisabled'::text) AS d_disabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'patchingEnabled'::text) AS d_enabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'workstationPatchingDisabled'::text) AS d_ws_disabled,
            bool_or(dcf.value_bool) FILTER (WHERE dcf.field_name = 'serverPatchingDisabled'::text) AS d_sv_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'patchingDisabled'::text) AS o_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'workstationPatchingDisabled'::text) AS o_ws_disabled,
            bool_or(ocf.value_bool) FILTER (WHERE ocf.field_name = 'serverPatchingDisabled'::text) AS o_sv_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'patchingDisabled'::text) AS l_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'workstationPatchingDisabled'::text) AS l_ws_disabled,
            bool_or(lcf.value_bool) FILTER (WHERE lcf.field_name = 'serverPatchingDisabled'::text) AS l_sv_disabled,
            max(nl_1.effective_policy_name) AS effective_policy_name
           FROM ninja_linked nl_1
             LEFT JOIN device_cf dcf ON dcf.entity_id = nl_1.ninja_device_id
             LEFT JOIN organization_cf ocf ON ocf.entity_id = nl_1.organization_id
             LEFT JOIN location_cf lcf ON lcf.entity_id = nl_1.location_id
          GROUP BY nl_1.tenant_id, nl_1.device_id
        )
 SELECT d.tenant_id,
    d.id AS device_id,
    d.device_role,
        CASE
            WHEN nl.ninja_device_id IS NULL THEN 'Unmanaged'::character varying
            WHEN d.os_group::text <> 'Windows'::text THEN 'Unmanaged'::character varying
            WHEN COALESCE(sig.d_disabled, sig.o_disabled, sig.l_disabled, false) THEN 'Excluded'::character varying
            WHEN COALESCE(sig.d_enabled, false) THEN 'Included'::character varying
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.d_ws_disabled, sig.o_ws_disabled, sig.l_ws_disabled, false) THEN 'Excluded'::character varying
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.d_sv_disabled, sig.o_sv_disabled, sig.l_sv_disabled, false) THEN 'Excluded'::character varying
            WHEN d.device_role::text = 'server'::text AND sig.effective_policy_name IS NOT NULL AND (EXISTS ( SELECT 1
               FROM operations.patching_scope_policy_allowlist a
              WHERE a.enabled AND a.policy_name::text = sig.effective_policy_name)) THEN 'Included'::character varying
            ELSE COALESCE(( SELECT def.effect
               FROM operations.patching_scope_default def
              WHERE def.device_role::text = d.device_role::text AND def.enabled), 'Unmanaged'::character varying)
        END AS scope_derived,
        CASE
            WHEN nl.ninja_device_id IS NULL THEN 'no-ninja-link'::text
            WHEN d.os_group::text <> 'Windows'::text THEN 'os-group-not-windows'::text
            WHEN COALESCE(sig.d_disabled, false) THEN 'device.patchingDisabled'::text
            WHEN COALESCE(sig.o_disabled, false) THEN 'organization.patchingDisabled'::text
            WHEN COALESCE(sig.l_disabled, false) THEN 'location.patchingDisabled'::text
            WHEN COALESCE(sig.d_enabled, false) THEN 'device.patchingEnabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.d_ws_disabled, false) THEN 'device.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.o_ws_disabled, false) THEN 'organization.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'workstation'::text AND COALESCE(sig.l_ws_disabled, false) THEN 'location.workstationPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.d_sv_disabled, false) THEN 'device.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.o_sv_disabled, false) THEN 'organization.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND COALESCE(sig.l_sv_disabled, false) THEN 'location.serverPatchingDisabled'::text
            WHEN d.device_role::text = 'server'::text AND sig.effective_policy_name IS NOT NULL AND (EXISTS ( SELECT 1
               FROM operations.patching_scope_policy_allowlist a
              WHERE a.enabled AND a.policy_name::text = sig.effective_policy_name)) THEN 'policy-allowlist:'::text || sig.effective_policy_name
            ELSE 'default:'::text || COALESCE(NULLIF(d.device_role::text, ''::text), 'unknown'::text)
        END AS scope_reason,
    now() AS computed_at
   FROM operations.devices d
     LEFT JOIN ninja_linked nl ON nl.device_id = d.id AND nl.tenant_id = d.tenant_id
     LEFT JOIN signals sig ON sig.device_id = d.id AND sig.tenant_id = d.tenant_id
  WHERE d.deleted_at IS NULL;

CREATE UNIQUE INDEX idx_device_patching_scope_current_pk
    ON operations.device_patching_scope_current (tenant_id, device_id);
CREATE INDEX idx_device_patching_scope_current_scope
    ON operations.device_patching_scope_current (tenant_id, scope_derived);

ALTER MATERIALIZED VIEW operations.device_patching_scope_current
    OWNER TO operations_migrate;

-- Restores the matview's deployed ACL exactly.
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.device_patching_scope_current
    TO operations_app;
GRANT SELECT ON operations.device_patching_scope_current
    TO operations_readonly, metabase_ro, ninja_ingest;
"""


RESTORE_SQL = r"""
DO $block$
DECLARE
    rec  record;
    stmt text;
BEGIN
    SELECT * INTO rec FROM _vdev_stash;

    EXECUTE format(
        'CREATE VIEW operations.v_device %s AS %s',
        CASE WHEN rec.reloptions IS NULL THEN ''
             ELSE 'WITH (' || array_to_string(rec.reloptions, ', ') || ')'
        END,
        rec.viewdef
    );
    EXECUTE format('ALTER VIEW operations.v_device OWNER TO %I', rec.owner);

    FOREACH stmt IN ARRAY COALESCE(rec.grants, ARRAY[]::text[]) LOOP
        EXECUTE stmt;
    END LOOP;
END
$block$;

DROP TABLE _vdev_stash;
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0120_require_entity_anchors"),
    ]

    operations: ClassVar = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(CREATE_VIEW_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(PARITY_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(CAPTURE_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(REPLACE_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(RESTORE_SQL, migrations.RunSQL.noop),
            ],
            # DeviceLink is replaced by the unmanaged DeviceSourceLink. The
            # table drop happens in REPLACE_SQL above, in dependency order, so
            # Django must only forget the model rather than emit its own DROP.
            state_operations=[
                migrations.DeleteModel(name="DeviceLink"),
                # State-only: `managed = False` means Django emits no DDL for
                # this model. The relation itself is created by
                # CREATE_VIEW_SQL above.
                migrations.CreateModel(
                    name="DeviceSourceLink",
                    fields=[
                        ("id", models.UUIDField(primary_key=True, serialize=False)),
                        ("external_id", models.CharField(max_length=240)),
                        ("external_namespace", models.CharField(max_length=120)),
                        ("first_seen_at", models.DateTimeField(blank=True, null=True)),
                        ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                        ("missing_since", models.DateTimeField(blank=True, null=True)),
                        ("match_method", models.CharField(max_length=32)),
                        (
                            "match_confidence",
                            models.DecimalField(decimal_places=3, max_digits=4),
                        ),
                    ],
                    options={
                        "db_table": "v_device_source_link",
                        "managed": False,
                    },
                ),
            ],
        ),
    ]
