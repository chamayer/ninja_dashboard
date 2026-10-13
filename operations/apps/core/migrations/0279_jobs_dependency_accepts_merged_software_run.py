"""Let a workflow edge attach to a broader software run that absorbed its request.

``jobs_request_software_v1`` merges a software request into any queued or
running run of the same family with an equal or higher rank, so a request for
``software-classify-only`` can return a queued ``software-classify-full`` run.
``jobs_add_revision_dependency_v1`` then rejected the edge because the registry
names ``software-classify-only`` as the successor, which deferred
``software-queue-drain`` and failed other software follow-ups with "Jobs revision
dependency context is invalid".

The run that absorbed the request does the requested work and more, so waiting
on the prerequisite is still correct.  This accepts a dependent of the same
supersession family whose rank is at least the declared successor's rank, and
keeps every other check (scope, revision name, failure rule) unchanged.
"""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_PREVIOUS = importlib.import_module("apps.core.migrations.0272_source_to_tenant_workflow_scope")

_OLD_MATCH = """      JOIN operations.operator_job_runs dependent
        ON dependent.tenant_id = prerequisite.tenant_id
       AND dependent.id = p_dependent_run_id
      CROSS JOIN LATERAL jsonb_array_elements(
          COALESCE(definition.metadata->'successors', '[]'::jsonb)
      ) AS edge(contract)
     WHERE prerequisite.tenant_id = p_tenant_id
       AND prerequisite.id = p_prerequisite_run_id
       AND edge.contract->>'successor' = dependent.job_key
"""

_NEW_MATCH = """      JOIN operations.operator_job_runs dependent
        ON dependent.tenant_id = prerequisite.tenant_id
       AND dependent.id = p_dependent_run_id
      LEFT JOIN operations.job_definition_versions dependent_definition
        ON dependent_definition.definition_key = dependent.job_key
       AND dependent_definition.definition_digest = dependent.definition_digest
      CROSS JOIN LATERAL jsonb_array_elements(
          COALESCE(definition.metadata->'successors', '[]'::jsonb)
      ) AS edge(contract)
     WHERE prerequisite.tenant_id = p_tenant_id
       AND prerequisite.id = p_prerequisite_run_id
       AND (
           edge.contract->>'successor' = dependent.job_key
           OR (
               -- A run that absorbed the request: same family, rank not lower.
               dependent_definition.metadata->>'supersession_family' = 'software-classifier'
               AND dependent_definition.metadata->>'supersession_rank' ~ '^[1-9][0-9]*$'
               AND (dependent_definition.metadata->>'supersession_rank')::integer >= COALESCE((
                   SELECT max((successor_definition.metadata->>'supersession_rank')::integer)
                     FROM operations.job_definition_versions successor_definition
                    WHERE successor_definition.definition_key = edge.contract->>'successor'
                      AND successor_definition.metadata->>'supersession_family'
                          = 'software-classifier'
                      AND successor_definition.metadata->>'supersession_rank'
                          ~ '^[1-9][0-9]*$'
               ), 2147483647)
           )
       )
"""

assert _OLD_MATCH in _PREVIOUS.FORWARD_SQL, "0272 function text changed"

FORWARD_SQL = _PREVIOUS.FORWARD_SQL.replace(_OLD_MATCH, _NEW_MATCH)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0278_register_ruon_agent_source"),
    ]
    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, _PREVIOUS.FORWARD_SQL),
    ]
