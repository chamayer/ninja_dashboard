"""One read model for a finding's operator state: ``operations.finding_states``.

The Issues page used to build a state for every one of the 39,000 active findings in
Python (10 of its 16 seconds) in order to filter, count and label them. This view gives
the database that job. It is the stored roll-up (``findings.attention``, migration 0297)
with the three things that must be read live applied on top:

* pause (``snoozed_until``) and closed status;
* freshness: a stored value older than the active policy's freshness window, or never
  written, reads as pending;
* "critical takes priority": a needs-action finding of medium, low or info severity is
  blocked while a needs-action critical finding shares its computer or a participant.
  The critical finding it names is returned so the page can say which.

The view is read-only and ``security_invoker``, so row-level security applies to the
caller exactly as for the underlying tables. Nothing else is stored.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
/* The stored value with pause, closed status and freshness applied. A plain SQL function
 * so the planner inlines it and a query for a few findings reads only those findings. */
CREATE OR REPLACE FUNCTION operations.finding_live_attention(
    p_status text, p_snoozed_until timestamptz, p_attention text, p_attention_at timestamptz
) RETURNS text
LANGUAGE sql
STABLE
AS $function$
    SELECT CASE
        WHEN p_snoozed_until > now() THEN 'paused'
        WHEN p_status IN ('resolved', 'suppressed', 'wontfix') THEN ''
        WHEN p_attention IS NULL OR p_attention_at IS NULL
             OR p_attention_at < now() - COALESCE(
                    (SELECT (policy->>'freshness_hours')::integer
                       FROM operations.condition_policy_versions
                      WHERE active ORDER BY version DESC LIMIT 1), 24) * interval '1 hour'
            THEN 'pending'
        ELSE p_attention
    END
$function$;
ALTER FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz)
    OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.finding_live_attention(text, timestamptz, text, timestamptz)
    TO operations_app, ninja_ingest, operations_readonly;

CREATE OR REPLACE VIEW operations.finding_states
WITH (security_invoker = true) AS
SELECT f.id,
       f.tenant_id,
       f.finding_type_id,
       ft.name AS finding_type,
       f.severity,
       f.status,
       f.snoozed_until,
       f.subject_type,
       f.subject_id,
       CASE WHEN k.id IS NOT NULL THEN 'blocked' ELSE l.attention END AS attention,
       k.id AS critical_finding_id,
       k.finding_type AS critical_type,
       k.subject_id AS critical_subject_id
  FROM operations.findings f
  JOIN operations.finding_types ft ON ft.id = f.finding_type_id
  CROSS JOIN LATERAL (
        SELECT operations.finding_live_attention(
                   f.status, f.snoozed_until, f.attention, f.attention_at) AS attention
  ) l
  LEFT JOIN LATERAL (
        SELECT c.id, ct.name AS finding_type, c.subject_id
          FROM operations.findings c
          JOIN operations.finding_types ct ON ct.id = c.finding_type_id
         WHERE l.attention = 'needs_action'
           AND f.severity IN ('medium', 'low', 'info')
           AND c.tenant_id = f.tenant_id
           AND c.severity = 'critical'
           AND c.status IN ('open', 'acknowledged', 'investigating')
           AND operations.finding_live_attention(
                   c.status, c.snoozed_until, c.attention, c.attention_at) = 'needs_action'
           AND (
                (c.subject_type = f.subject_type AND c.subject_id = f.subject_id)
                OR EXISTS (
                    SELECT 1
                      FROM operations.condition_participants p
                      JOIN operations.condition_participants q
                        ON q.tenant_id = p.tenant_id AND q.row_kind = 'entity'
                       AND q.participant_role <> 'context'
                       AND q.participant_kind = p.participant_kind
                       AND q.participant_id = p.participant_id
                       AND q.finding_id = c.id
                     WHERE p.tenant_id = f.tenant_id AND p.row_kind = 'entity'
                       AND p.participant_role <> 'context' AND p.finding_id = f.id)
           )
         ORDER BY c.id
         LIMIT 1
  ) k ON TRUE;

ALTER VIEW operations.finding_states OWNER TO operations_migrate;
REVOKE ALL ON operations.finding_states FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.finding_states
    FROM operations_app, ninja_ingest, operations_readonly, metabase_ro;
GRANT SELECT ON operations.finding_states TO operations_app, ninja_ingest, operations_readonly;
"""

REVERSE_SQL = """
DROP VIEW IF EXISTS operations.finding_states;
DROP FUNCTION IF EXISTS operations.finding_live_attention(text, timestamptz, text, timestamptz);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0297_finding_attention"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.CreateModel(
            name="FindingState",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("tenant_id", models.IntegerField()),
                ("finding_type_id", models.IntegerField()),
                ("finding_type", models.CharField(max_length=120)),
                ("severity", models.CharField(max_length=16)),
                ("status", models.CharField(max_length=24)),
                ("snoozed_until", models.DateTimeField(null=True)),
                ("subject_type", models.CharField(max_length=24)),
                ("subject_id", models.UUIDField()),
                ("attention", models.CharField(max_length=16)),
                ("critical_finding_id", models.UUIDField(null=True)),
                ("critical_type", models.CharField(max_length=120, null=True)),
                ("critical_subject_id", models.UUIDField(null=True)),
            ],
            options={"db_table": "finding_states", "managed": False},
        ),
    ]
