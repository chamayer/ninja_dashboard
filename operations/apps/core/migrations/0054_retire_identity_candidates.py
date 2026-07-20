"""Migration 0054 — retire operations.identity_candidates table.

Per ADR-0005 slice-C follow-through and the "findings live in the
standard table — no side tables per type" rule.

Identity conflicts now surface as `identity_conflict` Findings in the
standard `operations.findings` queue (see 0.66.0 + 0.66.1). The
merge/reject workflow that formerly lived on the
`identity_candidates_list` admin page is retired in favor of:

- Operator sees an `identity_conflict` Finding in the standard queue.
- Row exposes candidate device IDs and a "Merge candidates →" link
  when `candidate_count == 2`.
- Merge action is the generic `device_merge` view on the Devices
  surface (0.67.0) — invokable from anywhere with two Device IDs.

This migration drops the `operations.identity_candidates` table and
its RLS policy + grants. The Django model was removed in the same
release (0.68.0); this migration uses `SeparateDatabaseAndState` so
Django's model state loses the entity cleanly.

**Data loss note:** at retirement time, production had 12 rows in
`status='pending'`. These are dropped. Any *live* hostname conflict
those rows represented will be re-detected on the next resolver drain
and emitted as an `identity_conflict` Finding (per 0.66.x). Any stale
candidate whose underlying conflict has already been resolved simply
disappears — no false negative. Historic confirm/reject decisions
made through the retired admin page are preserved in
`operations.audit_log`.
"""

from __future__ import annotations

from django.db import migrations


_DROP_TABLE_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON operations.identity_candidates;
DROP TABLE IF EXISTS operations.identity_candidates;
"""

# Reverse is best-effort — recreates a bare table shape so the migration
# can be rolled back for schema-continuity purposes. The original DDL
# lives in migration 0014 / 0019.
_RECREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS operations.identity_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version INTEGER NOT NULL DEFAULT 1,
    tenant_id BIGINT NOT NULL REFERENCES operations.tenants(id),
    observation_id UUID,
    device_id_a UUID,
    device_id_b UUID,
    device_a_id UUID,
    device_b_id UUID,
    confidence VARCHAR(16),
    signals JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(16) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(120) DEFAULT ''
);
ALTER TABLE operations.identity_candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON operations.identity_candidates
    USING (tenant_id = current_setting('operations.tenant_id', true)::bigint);
"""


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0053_identity_conflict_auto_resolvable"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="IdentityCandidate"),
            ],
            database_operations=[
                migrations.RunSQL(_DROP_TABLE_SQL, _RECREATE_TABLE_SQL),
            ],
        ),
    ]
