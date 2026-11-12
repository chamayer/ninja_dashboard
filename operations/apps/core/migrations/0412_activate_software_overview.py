"""Activate the reviewed Software publication without waiting for future collection."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations


def frozen_sql(number, name):
    source = import_module(f"apps.core.migrations.{number}").FORWARD_SQL
    start = source.index(f"CREATE FUNCTION operations.{name}(")
    end = source.index("$fn$;", start) + len("$fn$;")
    return source[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


OLD_INPUTS = frozen_sql("0409_software_overview_publication_fence", "software_overview_inputs")
OLD_BEGIN = frozen_sql("0409_software_overview_publication_fence", "begin_software_overview")
OLD_PUBLISH = frozen_sql("0409_software_overview_publication_fence", "publish_software_overview")
OLD_READ = frozen_sql("0410_software_overview_protected_read", "read_software_overview")
OLD_CALCULATE = frozen_sql("0407_software_overview_aggregate", "refresh_software_overview")

# Collection attempts are not input publications. Failed device fetches retain
# prior inventory. Existing material-change targets and ownership dirtiness
# prevent publication until committed changes have been processed.
start = OLD_INPUTS.index("        VALUES (")
end = OLD_INPUTS.index("    ), latest AS MATERIALIZED", start)
INPUTS = OLD_INPUTS[:start] + """        VALUES ('software-classify'), ('software-classify-only'),
               ('software-classify-full'), ('software-catalog'), ('intel-matcher'),
               ('platform-evaluate'), ('computer-client-ownership'),
               ('computer-client-ownership-sweep')
""" + OLD_INPUTS[end:]
INPUTS = INPUTS.replace(
    "WHERE r.tenant_id = p_tenant AND (",
    "WHERE r.tenant_id = p_tenant AND r.status <> 'queued' "
    "AND (r.job_key NOT IN ('platform-evaluate', 'intel-matcher') "
    "OR r.status <> 'running' OR (r.wait_category = 'workflow' "
    "AND r.terminal_reason = 'handler_completed')) AND (",
    1,
).replace(
    "WHERE q.tenant_id = r.tenant_id AND q.run_id = r.id",
    "WHERE q.tenant_id = r.tenant_id AND q.run_id = r.id "
    "AND (q.trigger_kind <> 'dependency' OR q.actor_id IS NOT NULL)",
    1,
).replace(
    "AND r.status IN ('queued', 'running'))",
    "AND r.status IN ('queued', 'running') "
    "AND (r.status = 'running' OR requests.request_count > 0))",
    1,
).replace(
    "        'ownership_pending', EXISTS (",
    """        'classification_pending', EXISTS (
            SELECT 1 FROM operations.software_reclassification_targets
             WHERE tenant_id = p_tenant AND consumed_at IS NULL
        ) OR EXISTS (
            SELECT 1 FROM operations.operator_job_runs pending
             WHERE pending.tenant_id = p_tenant AND pending.status = 'queued'
               AND pending.job_key IN ('software-classify', 'software-classify-only', 'software-classify-full')
               AND EXISTS (SELECT 1 FROM operations.job_requests request
                            WHERE request.tenant_id = pending.tenant_id
                              AND request.run_id = pending.id AND request.actor_id IS NOT NULL)
        ),
        'ownership_pending', EXISTS (""",
    1,
).replace(
    "AND r.job_key IN (SELECT job_key FROM owners)",
    "AND r.job_key IN (SELECT job_key FROM owners) "
    "AND r.job_key NOT IN ('platform-evaluate', 'intel-matcher')",
    1,
)


def dirty_guard(sql, variable):
    marker = f"({variable}->>'ownership_pending')::boolean OR"
    assert sql.count(marker) == 1
    return sql.replace(
        marker,
        marker + f" coalesce(({variable}->>'classification_pending')::boolean, false) OR",
        1,
    )


BEGIN = dirty_guard(OLD_BEGIN, "inputs")
PUBLISH = dirty_guard(OLD_PUBLISH, "v_inputs")
READ = dirty_guard(OLD_READ, "inputs").replace(
    "AND id <> publication_run AND status IN ('queued', 'running')",
    """AND id <> publication_run AND status IN ('queued', 'running')
           AND NOT (status = 'queued' AND wait_category = 'dependency'
                    AND NOT EXISTS (
                        SELECT 1 FROM operations.job_requests request
                         WHERE request.tenant_id = p_tenant
                           AND request.run_id = operations.operator_job_runs.id
                           AND request.actor_id IS NOT NULL)
                    AND NOT EXISTS (
                        SELECT 1 FROM operations.operator_job_runs root
                         WHERE root.tenant_id = p_tenant
                           AND root.id = operations.operator_job_runs.root_run_id
                           AND root.requested_by_id IS NOT NULL))""",
    1,
)

# Certification belongs to this reviewed implementation. Every generation must
# still pass preparation, input-change and live-claim fences before it commits.
CALCULATE = OLD_CALCULATE.replace("'{}'::jsonb, false,", "'{}'::jsonb, true,", 1).replace(
    "input_watermarks = EXCLUDED.input_watermarks, contract_ready = false,",
    "input_watermarks = EXCLUDED.input_watermarks, contract_ready = true,",
    1,
)
assert CALCULATE != OLD_CALCULATE

FORWARD_SQL = "\n\n".join((INPUTS, BEGIN, PUBLISH, READ, CALCULATE))
REVERSE_SQL = "\n\n".join((OLD_INPUTS, OLD_BEGIN, OLD_PUBLISH, OLD_READ, OLD_CALCULATE))
REVERSE_SQL += "\nUPDATE operations.software_overview_current SET contract_ready=false WHERE tenant_id=1;"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0411_software_jobs_recovery_authorities"),
    ]
    operations: ClassVar = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
