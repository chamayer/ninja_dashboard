"""Binding-scoped collection health used by evaluators and platform health.

The durable source-refresh run is the collection lifecycle.  A source binding
is unhealthy only after that lifecycle has actually produced a failed/stalled
run or after a successful output has exceeded its configured freshness window.
New bindings without a source-managed result are intentionally not classified
as failures during the source-refresh transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class SourceCollectionProblem:
    binding_id: str
    source_name: str
    platform: str
    client_id: Any
    reason: str
    last_failure_at: datetime | None
    last_success_at: datetime | None
    error: str

    @property
    def condition_key(self) -> str:
        return f"source_failure:binding:{self.binding_id}"


def collection_problems(
    cur: Any, tenant_id: int, now: datetime
) -> list[SourceCollectionProblem]:
    """Return failed or overdue configured source bindings for one tenant."""
    cur.execute(
        """
        SELECT binding.id::text,
               source.name,
               COALESCE(NULLIF(instance.config->>'platform', ''), source.name),
               instance.client_id,
               binding.schedule,
               terminal.status,
               COALESCE(terminal.completed_at, terminal.started_at, terminal.requested_at),
               terminal.error,
               output.published_at
          FROM operations.source_bindings binding
          JOIN operations.source_instances instance
            ON instance.id = binding.source_instance_id
          JOIN operations.sources source ON source.id = instance.source_id
          LEFT JOIN LATERAL (
              SELECT status, completed_at, started_at, requested_at, error
                FROM operations.operator_job_runs
               WHERE tenant_id = binding.tenant_id
                 AND job_key = 'source-refresh'
                 AND scope_identity = 'source-binding:' || binding.id::text
                 AND status IN ('completed', 'failed', 'stalled', 'cancelled')
               ORDER BY requested_at DESC, id DESC
               LIMIT 1
          ) terminal ON TRUE
          LEFT JOIN LATERAL (
              SELECT published_at
                FROM operations.source_refresh_outputs
               WHERE tenant_id = binding.tenant_id
                 AND source_binding_id = binding.id
               ORDER BY published_at DESC, run_id DESC
               LIMIT 1
          ) output ON TRUE
         WHERE binding.tenant_id = %s
           AND binding.enabled = TRUE
           AND instance.enabled = TRUE
         ORDER BY source.name, binding.id
        """,
        (tenant_id,),
    )
    problems: list[SourceCollectionProblem] = []
    for (
        binding_id,
        source_name,
        platform,
        client_id,
        schedule,
        terminal_status,
        terminal_at,
        error,
        last_success_at,
    ) in cur.fetchall():
        reason = ""
        if terminal_status in {"failed", "stalled"}:
            reason = "The latest collection attempt did not finish."
        elif last_success_at is not None and now - last_success_at > _freshness_window(schedule):
            reason = "This source has not provided current data on its expected schedule."
        if reason:
            problems.append(
                SourceCollectionProblem(
                    binding_id=binding_id,
                    source_name=source_name,
                    platform=platform,
                    client_id=client_id,
                    reason=reason,
                    last_failure_at=terminal_at if terminal_status in {"failed", "stalled"} else None,
                    last_success_at=last_success_at,
                    error=(error or "")[:500],
                )
            )
    return problems


def blockers_for_platform(
    problems: list[SourceCollectionProblem], platform: str, client_id: Any
) -> tuple[str, ...]:
    """Root collection Issues that make this platform requirement unmeasurable.

    A tenant-wide source affects every client; a client-bound source affects
    only that client's requirements.  This keeps independent source evidence
    actionable.
    """
    return tuple(
        problem.condition_key
        for problem in problems
        if problem.platform == platform
        and (problem.client_id is None or problem.client_id == client_id)
    )


def _freshness_window(schedule: str | None) -> timedelta:
    """Twice the configured cadence, with the established eight-hour floor."""
    prefix, separator, raw_minutes = (schedule or "").partition(":")
    try:
        minutes = int(raw_minutes) if prefix == "interval" and separator else 8 * 60
    except ValueError:
        minutes = 8 * 60
    return timedelta(minutes=max(8 * 60, minutes * 2))
