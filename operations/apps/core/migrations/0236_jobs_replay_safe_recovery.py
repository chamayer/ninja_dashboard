"""Recover audited replay-safe Jobs holds without operator attestation."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE TABLE operations.job_recovery_policy_authorities (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    definition_key TEXT NOT NULL CHECK (length(definition_key) BETWEEN 1 AND 120),
    recovery_mode TEXT NOT NULL CHECK (recovery_mode IN ('replay_safe')),
    evidence_summary TEXT NOT NULL CHECK (length(evidence_summary) BETWEEN 20 AND 2000),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, definition_key)
);
ALTER TABLE operations.job_recovery_policy_authorities OWNER TO operations_migrate;
REVOKE ALL ON operations.job_recovery_policy_authorities
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.job_recovery_policy_authorities ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.job_recovery_policy_authorities FORCE ROW LEVEL SECURITY;
CREATE POLICY job_recovery_authority_tenant_isolation ON operations.job_recovery_policy_authorities
    USING (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

INSERT INTO operations.job_recovery_policy_authorities (
    tenant_id, definition_key, recovery_mode, evidence_summary
) VALUES
    (
        1, 'intel-epss', 'replay_safe',
        'The EPSS refresh only performs a transaction-scoped conditional update of existing CVE scores. A later replay converges to the current public EPSS feed and has no external mutation.'
    ),
    (
        1, 'software-classify-only', 'replay_safe',
        'Incremental software classification only reconciles Operations findings and exact-state markers in one database transaction. A later replay converges to the current installation and policy state and has no external mutation.'
    );

CREATE TABLE operations.job_recovery_policies (
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    definition_key TEXT NOT NULL CHECK (length(definition_key) BETWEEN 1 AND 120),
    definition_digest TEXT NOT NULL CHECK (definition_digest ~ '^[0-9a-f]{64}$'),
    recovery_mode TEXT NOT NULL CHECK (recovery_mode IN ('replay_safe')),
    evidence_summary TEXT NOT NULL CHECK (length(evidence_summary) BETWEEN 20 AND 2000),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, definition_key, definition_digest),
    FOREIGN KEY (definition_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest)
);
ALTER TABLE operations.job_recovery_policies OWNER TO operations_migrate;
REVOKE ALL ON operations.job_recovery_policies
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.job_recovery_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.job_recovery_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY job_recovery_policy_tenant_isolation ON operations.job_recovery_policies
    USING (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

CREATE TABLE operations.job_recovery_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id) CHECK (tenant_id = 1),
    run_id UUID NOT NULL,
    definition_key TEXT NOT NULL CHECK (length(definition_key) BETWEEN 1 AND 120),
    definition_digest TEXT NOT NULL CHECK (definition_digest ~ '^[0-9a-f]{64}$'),
    recovery_mode TEXT NOT NULL CHECK (recovery_mode IN ('replay_safe')),
    evidence_summary TEXT NOT NULL CHECK (length(evidence_summary) BETWEEN 20 AND 2000),
    released_claim_count INTEGER NOT NULL CHECK (released_claim_count > 0),
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, run_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES operations.operator_job_runs (tenant_id, id),
    FOREIGN KEY (definition_key, definition_digest)
        REFERENCES operations.job_definition_versions (definition_key, definition_digest)
);
ALTER TABLE operations.job_recovery_assessments OWNER TO operations_migrate;
REVOKE ALL ON operations.job_recovery_assessments
    FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
ALTER TABLE operations.job_recovery_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.job_recovery_assessments FORCE ROW LEVEL SECURITY;
CREATE POLICY job_recovery_assessment_tenant_isolation ON operations.job_recovery_assessments
    USING (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint)
    WITH CHECK (current_user = 'operations_migrate'
        OR tenant_id = NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint);

INSERT INTO operations.job_recovery_policies (
    tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
) SELECT 1, seeded.definition_key, seeded.definition_digest,
         'replay_safe', authority.evidence_summary
    FROM (VALUES
        (
            'intel-epss',
            '72ea9c43081243dcb66e8d39c278656fc50d2a119c47cc2284fb7a85340d09b5'
        ),
        (
            'software-classify-only',
            'e0978da8ef740e9fc95f1fc08f11bc93eca937473d2202f778415f8ed962156a'
        )
    ) AS seeded(definition_key, definition_digest)
    JOIN operations.job_recovery_policy_authorities AS authority
      ON authority.tenant_id = 1
     AND authority.definition_key = seeded.definition_key
     AND authority.recovery_mode = 'replay_safe'
    JOIN operations.job_definition_versions AS definition_version
      ON definition_version.definition_key = seeded.definition_key
     AND definition_version.definition_digest = seeded.definition_digest
ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;

CREATE FUNCTION operations.jobs_register_recovery_policy_v1(
    p_tenant_id BIGINT, p_definition_key TEXT, p_definition_digest TEXT,
    p_evidence_summary TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_definition_key IS NULL OR p_definition_digest IS NULL
       OR p_evidence_summary IS NULL OR length(p_evidence_summary) NOT BETWEEN 20 AND 2000
       OR NOT EXISTS (
           SELECT 1 FROM operations.job_definition_versions
            WHERE definition_key = p_definition_key AND definition_digest = p_definition_digest
       )
       OR NOT EXISTS (
           SELECT 1 FROM operations.job_recovery_policy_authorities
            WHERE tenant_id = p_tenant_id AND definition_key = p_definition_key
              AND recovery_mode = 'replay_safe' AND evidence_summary = p_evidence_summary
       )
    THEN RAISE EXCEPTION 'Jobs recovery policy registration is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    INSERT INTO operations.job_recovery_policies (
        tenant_id, definition_key, definition_digest, recovery_mode, evidence_summary
    ) VALUES (
        p_tenant_id, p_definition_key, p_definition_digest, 'replay_safe', p_evidence_summary
    ) ON CONFLICT (tenant_id, definition_key, definition_digest) DO NOTHING;
END
$function$;

CREATE FUNCTION operations.jobs_reconcile_replay_safe_containment_v1(
    p_tenant_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT; v_count BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1 THEN
        RAISE EXCEPTION 'Jobs recovery reconciliation context is invalid';
    END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);

    WITH eligible AS (
        SELECT job.id AS run_id, job.job_key, job.definition_digest,
               policy.recovery_mode, policy.evidence_summary,
               count(claim.id)::integer AS claim_count
          FROM operations.operator_job_runs AS job
          JOIN operations.job_recovery_policies AS policy
            ON policy.tenant_id = job.tenant_id
           AND policy.definition_key = job.job_key
           AND policy.definition_digest = job.definition_digest
           AND policy.recovery_mode = 'replay_safe'
          JOIN operations.job_resource_claims AS claim
            ON claim.tenant_id = job.tenant_id
           AND claim.run_id = job.id
           AND claim.state = 'contained'
          LEFT JOIN operations.job_recovery_assessments AS assessment
            ON assessment.tenant_id = job.tenant_id AND assessment.run_id = job.id
         WHERE job.tenant_id = p_tenant_id
           AND job.status = 'stalled'
           AND assessment.run_id IS NULL
         GROUP BY job.id, job.job_key, job.definition_digest,
                  policy.recovery_mode, policy.evidence_summary
    ), assessed AS (
        INSERT INTO operations.job_recovery_assessments (
            tenant_id, run_id, definition_key, definition_digest, recovery_mode,
            evidence_summary, released_claim_count
        )
        SELECT p_tenant_id, run_id, job_key, definition_digest, recovery_mode,
               evidence_summary, claim_count
          FROM eligible
        ON CONFLICT (tenant_id, run_id) DO NOTHING
        RETURNING run_id, released_claim_count
    ), released AS (
        UPDATE operations.job_resource_claims AS claim
           SET state = 'released', released_at = now(),
               release_reason = 'Automated recovery: audited replay-safe handler.'
          FROM assessed
         WHERE claim.tenant_id = p_tenant_id
           AND claim.run_id = assessed.run_id
           AND claim.state = 'contained'
        RETURNING claim.run_id
    ), events AS (
        INSERT INTO operations.operator_job_events (
            tenant_id, job_id, event_type, stage, detail
        )
        SELECT p_tenant_id, assessed.run_id, 'recovery_reconciled', 'Needs attention',
               'The system released contained work after verifying the handler is audited for safe replay.'
          FROM assessed
        WHERE EXISTS (SELECT 1 FROM released WHERE released.run_id = assessed.run_id)
    )
    SELECT count(DISTINCT run_id) INTO v_count FROM released;
    RETURN v_count;
END
$function$;

CREATE FUNCTION operations.jobs_recovery_diagnostics_v1(
    p_tenant_id BIGINT, p_section TEXT, p_limit INTEGER, p_offset INTEGER
) RETURNS TABLE(total_count BIGINT, item JSONB)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, operations
AS $function$
DECLARE v_context_tenant BIGINT;
BEGIN
    v_context_tenant := NULLIF(current_setting('operations.tenant_id', TRUE), '')::bigint;
    IF v_context_tenant IS NULL OR v_context_tenant <> p_tenant_id OR p_tenant_id <> 1
       OR p_section IS NULL OR p_section NOT IN (
           'recovery_authorities', 'recovery_policies', 'recovery_assessments'
       )
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
       OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
    THEN RAISE EXCEPTION 'Jobs recovery diagnostics context is invalid'; END IF;
    PERFORM set_config('operations.tenant_id', p_tenant_id::text, TRUE);
    IF p_section = 'recovery_authorities' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, definition_key, recovery_mode,
                   evidence_summary, reviewed_at
              FROM operations.job_recovery_policy_authorities
             WHERE tenant_id = p_tenant_id
             ORDER BY definition_key LIMIT p_limit OFFSET p_offset
        ) page;
    ELSIF p_section = 'recovery_policies' THEN
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, definition_key, definition_digest,
                   recovery_mode, evidence_summary, reviewed_at
              FROM operations.job_recovery_policies
             WHERE tenant_id = p_tenant_id
             ORDER BY definition_key, definition_digest LIMIT p_limit OFFSET p_offset
        ) page;
    ELSE
        RETURN QUERY SELECT page.row_count, to_jsonb(page) - 'row_count' FROM (
            SELECT count(*) OVER () AS row_count, run_id, definition_key,
                   definition_digest, recovery_mode, evidence_summary,
                   released_claim_count, assessed_at
              FROM operations.job_recovery_assessments
             WHERE tenant_id = p_tenant_id
             ORDER BY assessed_at DESC, run_id DESC LIMIT p_limit OFFSET p_offset
        ) page;
    END IF;
END
$function$;

ALTER FUNCTION operations.jobs_reconcile_replay_safe_containment_v1(BIGINT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_register_recovery_policy_v1(BIGINT, TEXT, TEXT, TEXT)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.jobs_recovery_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_reconcile_replay_safe_containment_v1(BIGINT),
    operations.jobs_register_recovery_policy_v1(BIGINT, TEXT, TEXT, TEXT),
    operations.jobs_recovery_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
FROM PUBLIC, operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT EXECUTE ON FUNCTION operations.jobs_reconcile_replay_safe_containment_v1(BIGINT)
    TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_register_recovery_policy_v1(BIGINT, TEXT, TEXT, TEXT)
    TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.jobs_recovery_diagnostics_v1(BIGINT, TEXT, INTEGER, INTEGER)
    TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0235_jobs_recovery_evidence_gate"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
