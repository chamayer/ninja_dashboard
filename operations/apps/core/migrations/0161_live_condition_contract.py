"""Persist the conditions contract without replacing legacy findings."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = """
CREATE TABLE operations.condition_policy_versions (
    version TEXT PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    policy JSONB NOT NULL CHECK (jsonb_typeof(policy) = 'object'),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_condition_policy_one_active
    ON operations.condition_policy_versions (active) WHERE active;

CREATE TABLE operations.condition_policies (
    policy_version TEXT NOT NULL REFERENCES operations.condition_policy_versions(version),
    finding_type_id SMALLINT NOT NULL REFERENCES operations.finding_types(id),
    type_name TEXT NOT NULL,
    category TEXT NOT NULL,
    grouped_type TEXT NOT NULL,
    label TEXT NOT NULL,
    definition JSONB NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
    offline_days INTEGER NOT NULL CHECK (offline_days > 0),
    freshness_hours INTEGER NOT NULL CHECK (freshness_hours > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_version, finding_type_id),
    UNIQUE (policy_version, type_name)
);

CREATE TABLE operations.condition_assessments (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    row_kind TEXT NOT NULL CHECK (row_kind IN ('entity', 'admin')),
    finding_id UUID NOT NULL,
    participant_kind TEXT NOT NULL DEFAULT 'condition',
    participant_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000',
    participant_role TEXT NOT NULL DEFAULT 'aggregate',
    condition_identity TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    coverage JSONB NOT NULL CHECK (jsonb_typeof(coverage) = 'object'),
    response JSONB NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    reevaluation_key TEXT NOT NULL,
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (
        tenant_id, row_kind, finding_id,
        participant_kind, participant_id, participant_role
    ),
    CHECK (
        (participant_kind = 'condition'
         AND participant_id = '00000000-0000-0000-0000-000000000000'
         AND participant_role = 'aggregate')
        OR participant_kind <> 'condition'
    )
);

CREATE TABLE operations.condition_participants (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    row_kind TEXT NOT NULL CHECK (row_kind IN ('entity', 'admin')),
    finding_id UUID NOT NULL,
    participant_kind TEXT NOT NULL,
    participant_id UUID NOT NULL,
    participant_role TEXT NOT NULL,
    PRIMARY KEY (tenant_id, row_kind, finding_id, participant_kind, participant_id, participant_role)
);

CREATE INDEX idx_condition_assessments_tenant_response
    ON operations.condition_assessments (tenant_id, (response->>'disposition'));
CREATE INDEX idx_condition_participants_lookup
    ON operations.condition_participants (tenant_id, participant_kind, participant_id);

ALTER TABLE operations.condition_policies OWNER TO operations_migrate;
ALTER TABLE operations.condition_policy_versions OWNER TO operations_migrate;
ALTER TABLE operations.condition_assessments OWNER TO operations_migrate;
ALTER TABLE operations.condition_participants OWNER TO operations_migrate;

ALTER TABLE operations.condition_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.condition_assessments FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.condition_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.condition_participants FORCE ROW LEVEL SECURITY;
CREATE POLICY condition_assessment_tenant_isolation ON operations.condition_assessments
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT);
CREATE POLICY condition_participant_tenant_isolation ON operations.condition_participants
    USING (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT)
    WITH CHECK (tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT);

CREATE FUNCTION operations.reject_condition_policy_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF TG_TABLE_NAME = 'condition_policy_versions' AND current_user = 'operations_migrate'
       AND TG_OP = 'UPDATE'
       AND OLD.version = NEW.version
       AND OLD.digest = NEW.digest
       AND OLD.policy IS NOT DISTINCT FROM NEW.policy
       AND OLD.created_at = NEW.created_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'condition policies are immutable; create a new policy version';
END
$$;
ALTER FUNCTION operations.reject_condition_policy_change() OWNER TO operations_migrate;
CREATE TRIGGER condition_policy_immutable
    BEFORE UPDATE OR DELETE ON operations.condition_policies
    FOR EACH ROW EXECUTE FUNCTION operations.reject_condition_policy_change();
CREATE TRIGGER condition_policy_version_immutable
    BEFORE UPDATE OR DELETE ON operations.condition_policy_versions
    FOR EACH ROW EXECUTE FUNCTION operations.reject_condition_policy_change();

CREATE FUNCTION operations.create_condition_policy_version(
    p_version TEXT, p_digest TEXT, p_policy JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE item JSONB;
BEGIN
    IF p_version IS NULL OR p_version = '' OR p_digest IS NULL OR p_policy IS NULL
       OR jsonb_typeof(p_policy) <> 'object' THEN
        RAISE EXCEPTION 'Invalid condition policy document';
    END IF;
    IF jsonb_array_length(COALESCE(p_policy->'definitions', '[]'::jsonb))
       <> (SELECT count(*) FROM operations.finding_types) THEN
        RAISE EXCEPTION 'Condition policy must contain every registered finding type';
    END IF;
    INSERT INTO operations.condition_policy_versions(version, digest, policy, active)
    VALUES (p_version, p_digest, p_policy, FALSE);
    FOR item IN SELECT value FROM jsonb_array_elements(p_policy->'definitions') LOOP
        INSERT INTO operations.condition_policies
            (policy_version, finding_type_id, type_name, category, grouped_type,
             label, definition, offline_days, freshness_hours)
        SELECT p_version, ft.id, item->>'name', item->>'category', item->>'type',
               item->>'label', item, (p_policy->>'offline_days')::INTEGER,
               (p_policy->>'freshness_hours')::INTEGER
          FROM operations.finding_types ft
         WHERE ft.name = item->>'name';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Condition type is not registered: %', item->>'name';
        END IF;
    END LOOP;
    IF (SELECT count(*) FROM operations.condition_policies WHERE policy_version = p_version)
       <> (SELECT count(*) FROM operations.finding_types) THEN
        RAISE EXCEPTION 'Condition policy does not cover every registered finding type';
    END IF;
END
$$;
CREATE FUNCTION operations.activate_condition_policy_version(p_version TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM operations.condition_policy_versions
                   WHERE version = p_version) THEN
        RAISE EXCEPTION 'Unknown condition policy version: %', p_version;
    END IF;
    UPDATE operations.condition_policy_versions SET active = FALSE WHERE active;
    UPDATE operations.condition_policy_versions SET active = TRUE WHERE version = p_version;
END
$$;
ALTER FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.activate_condition_policy_version(TEXT)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB),
    operations.activate_condition_policy_version(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.create_condition_policy_version(TEXT, TEXT, JSONB),
    operations.activate_condition_policy_version(TEXT) TO operations_app;

CREATE VIEW operations.v_condition_assessment_current
WITH (security_barrier = true, security_invoker = true) AS
SELECT a.tenant_id, a.row_kind, a.finding_id,
       a.participant_kind, a.participant_id, a.participant_role,
       a.condition_identity,
       a.policy_version, a.coverage, a.response, a.reevaluation_key, a.assessed_at
  FROM operations.condition_assessments a
 WHERE a.tenant_id = NULLIF(current_setting('operations.tenant_id', true), '')::BIGINT;

REVOKE ALL ON operations.condition_policy_versions, operations.condition_policies,
    operations.condition_assessments, operations.condition_participants
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.condition_policy_versions, operations.condition_policies TO operations_app, ninja_ingest,
    operations_readonly, metabase_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.condition_assessments,
    operations.condition_participants TO operations_app, ninja_ingest;
GRANT SELECT ON operations.condition_assessments,
    operations.condition_participants TO operations_readonly, metabase_ro;
GRANT SELECT ON operations.v_condition_assessment_current TO operations_app,
    ninja_ingest, operations_readonly, metabase_ro;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_condition_assessment_current
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
"""

BOOTSTRAP_VERSION = "conditions-shadow-1"
BOOTSTRAP_DIGEST = "5e9b47350aabfc45b6cd21fea2bfd6e591ec9826886187ddfcfe0d6a7a031c40"
BOOTSTRAP_PAYLOAD = "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"

REVERSE_SQL = """
DROP VIEW IF EXISTS operations.v_condition_assessment_current;
DROP FUNCTION IF EXISTS operations.create_condition_policy_version(TEXT, TEXT, JSONB);
DROP FUNCTION IF EXISTS operations.activate_condition_policy_version(TEXT);
DROP FUNCTION IF EXISTS operations.reject_condition_policy_change();
DROP TABLE IF EXISTS operations.condition_participants;
DROP TABLE IF EXISTS operations.condition_assessments;
DROP TABLE IF EXISTS operations.condition_policies;
DROP TABLE IF EXISTS operations.condition_policy_versions;
"""


def seed_policies(apps, schema_editor):
    FindingType = apps.get_model("operations", "FindingType")
    profile = json.loads(zlib.decompress(base64.b64decode(BOOTSTRAP_PAYLOAD)))
    digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    if profile.get("version") != BOOTSTRAP_VERSION or digest != BOOTSTRAP_DIGEST:
        raise RuntimeError("The migration bootstrap profile changed; create a new policy migration")
    types = FindingType.objects.in_bulk(
        [item["name"] for item in profile["definitions"]], field_name="name"
    )
    missing = sorted(item["name"] for item in profile["definitions"] if item["name"] not in types)
    if missing:
        raise RuntimeError(f"Cannot seed condition policy for unregistered types: {missing}")
    rows = []
    for definition in profile["definitions"]:
        finding_type = types.get(definition["name"])
        if finding_type is None:
            continue
        rows.append(
            (
                finding_type.pk,
                definition["name"],
                definition["category"],
                definition["type"],
                definition["label"],
                profile["version"],
                json.dumps(definition, separators=(",", ":")),
                profile["offline_days"],
                profile["freshness_hours"],
            )
        )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO operations.condition_policy_versions
            (version, digest, policy, active) VALUES (%s, %s, %s::jsonb, TRUE)""",
            (
                profile["version"],
                digest,
                json.dumps(profile, separators=(",", ":")),
            ),
        )
        cursor.executemany(
            """INSERT INTO operations.condition_policies
            (finding_type_id, type_name, category, grouped_type, label,
             policy_version, definition, offline_days, freshness_hours)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            rows,
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0160_source_action_requests"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ConditionPolicyVersion",
                    fields=[
                        (
                            "version",
                            models.CharField(max_length=120, primary_key=True, serialize=False),
                        ),
                        ("digest", models.CharField(max_length=64, unique=True)),
                        ("policy", models.JSONField()),
                        ("active", models.BooleanField(default=False)),
                        ("created_at", models.DateTimeField()),
                    ],
                    options={
                        "db_table": "condition_policy_versions",
                        "managed": False,
                        "ordering": ("-version",),
                    },
                )
            ]
        ),
        migrations.RunPython(seed_policies, migrations.RunPython.noop),
    ]
