"""Withdraw retired Ninja ``ninja_main`` device evidence safely.

The default mode is a read-only aggregate measurement. Apply mode requires the
operator to pin both the eligible count and deterministic identity-set digest
reported by a reviewed dry run. It updates only current/history presence state;
canonical devices, source links, rollups, raw evidence, and decisions are not
mutation targets.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any

from ingest import db
from ingest.observation_runs import observed_identity_summary

NINJA_SOURCE_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
NINJA_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")
RETIRED_SNAPSHOT_SCOPE = "ninja_main"


class StaleScopeBlocked(RuntimeError):
    """Raised without source identifiers when the correction cannot proceed."""


@dataclass(frozen=True)
class StaleScopeResult:
    tenant_id: int
    active_records: int
    eligible_records: int
    eligible_identity_digest: str
    blocked_records: int
    shape_blockers: int
    provenance_blockers: int
    missing_legacy_device_blockers: int
    current_legacy_device_blockers: int
    withdrawal_boundary_blockers: int
    open_history_blockers: int
    already_corrected_records: int
    already_corrected_identity_digest: str
    updated_current_rows: int
    closed_history_rows: int
    apply: bool

    @property
    def blocker_count(self) -> int:
        return self.blocked_records


def _assert_source_provenance(cur: Any, *, tenant_id: int) -> None:
    cur.execute(
        """
        SELECT COUNT(*)
          FROM operations.source_bindings b
          JOIN operations.source_instances i
            ON i.id = b.source_instance_id
           AND i.tenant_id = b.tenant_id
          JOIN operations.sources s ON s.id = i.source_id
         WHERE b.id = %s
           AND b.tenant_id = %s
           AND b.source_instance_id = %s
           AND lower(s.name) = 'ninja'
        """,
        (NINJA_SOURCE_BINDING_ID, tenant_id, NINJA_SOURCE_INSTANCE_ID),
    )
    if cur.fetchone() != (1,):
        raise StaleScopeBlocked("Ninja source provenance is not uniquely configured")


def _target_rows(cur: Any, *, tenant_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT
            c.observation_id,
            c.source_binding_id,
            c.source_instance_id,
            c.last_seen_binding_id,
            c.external_namespace,
            c.parent_external_namespace,
            c.parent_external_id,
            c.external_id,
            c.platform,
            c.observed_at,
            c.last_seen_at,
            c.last_received_at,
            c.withdrawn_at,
            c.last_snapshot_run_id,
            c.material_hash,
            c.material_projection_version,
            d.id AS legacy_device_id,
            d.is_current AS legacy_is_current,
            d.missing_since,
            history.open_count,
            history.valid_open_count
          FROM operations.entity_observation_current c
          LEFT JOIN ninja_core.devices d ON d.id::text = c.external_id
          LEFT JOIN LATERAL (
              SELECT
                  COUNT(*) FILTER (WHERE h.effective_to IS NULL) AS open_count,
                  COUNT(*) FILTER (
                      WHERE h.effective_to IS NULL
                        AND h.active IS TRUE
                        AND d.missing_since IS NOT NULL
                        AND h.effective_from < d.missing_since
                        AND h.material_hash = c.material_hash
                        AND h.material_projection_version =
                            c.material_projection_version
                  ) AS valid_open_count
                FROM operations.entity_observation_history h
               WHERE h.tenant_id = c.tenant_id
                 AND h.source_instance_id = c.source_instance_id
                 AND h.external_namespace = c.external_namespace
                 AND h.parent_external_namespace =
                     c.parent_external_namespace
                 AND h.parent_external_id = c.parent_external_id
                 AND h.external_id = c.external_id
          ) history ON TRUE
         WHERE c.tenant_id = %s
           AND c.source_instance_id = %s
           AND c.external_namespace = 'device'
           AND c.snapshot_scope = %s
           AND c.active IS TRUE
         ORDER BY c.external_id
        """,
        (tenant_id, NINJA_SOURCE_INSTANCE_ID, RETIRED_SNAPSHOT_SCOPE),
    )
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, values, strict=True)) for values in cur.fetchall()]


def _blockers(row: dict[str, Any]) -> dict[str, bool]:
    boundary = row["missing_since"]
    # Receipt time is collector provenance, not source evidence time. These
    # rows were restored after their historical missing_since boundary, so a
    # late receipt must not make a valid source withdrawal appear out of order.
    latest_evidence = max(row["observed_at"], row["last_seen_at"])
    return {
        "shape": (
            str(row["platform"]).casefold() != "ninja"
            or row["parent_external_namespace"] != ""
            or row["parent_external_id"] != ""
            or row["material_projection_version"] != 1
            or row["last_snapshot_run_id"] is not None
            or row["withdrawn_at"] is not None
        ),
        "provenance": (
            row["source_binding_id"] != NINJA_SOURCE_BINDING_ID
            or row["last_seen_binding_id"] != NINJA_SOURCE_BINDING_ID
        ),
        "missing_legacy": row["legacy_device_id"] is None,
        "current_legacy": row["legacy_is_current"] is not False,
        "boundary": boundary is None or boundary <= latest_evidence,
        "history": row["open_count"] != 1 or row["valid_open_count"] != 1,
    }


def _already_corrected_rows(cur: Any, *, tenant_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT c.source_instance_id, c.external_namespace,
               c.parent_external_namespace, c.parent_external_id, c.external_id
          FROM operations.entity_observation_current c
          JOIN ninja_core.devices d ON d.id::text = c.external_id
         WHERE c.tenant_id = %s
           AND c.source_instance_id = %s
           AND c.external_namespace = 'device'
           AND c.snapshot_scope = %s
           AND c.active IS FALSE
           AND c.withdrawn_at = d.missing_since
           AND d.is_current IS FALSE
           AND lower(c.platform) = 'ninja'
           AND c.parent_external_namespace = ''
           AND c.parent_external_id = ''
           AND c.source_binding_id = %s
           AND c.last_seen_binding_id = %s
           AND c.material_projection_version = 1
           AND c.last_snapshot_run_id IS NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM operations.entity_observation_history h
                WHERE h.tenant_id = c.tenant_id
                  AND h.source_instance_id = c.source_instance_id
                  AND h.external_namespace = c.external_namespace
                  AND h.parent_external_namespace =
                      c.parent_external_namespace
                  AND h.parent_external_id = c.parent_external_id
                  AND h.external_id = c.external_id
                  AND h.effective_to IS NULL
           )
           AND EXISTS (
               SELECT 1
                 FROM operations.entity_observation_history h
                WHERE h.tenant_id = c.tenant_id
                  AND h.source_instance_id = c.source_instance_id
                  AND h.external_namespace = c.external_namespace
                  AND h.parent_external_namespace =
                      c.parent_external_namespace
                  AND h.parent_external_id = c.parent_external_id
                  AND h.external_id = c.external_id
                  AND h.effective_to = c.withdrawn_at
                  AND h.active IS TRUE
                  AND h.material_hash = c.material_hash
                  AND h.material_projection_version =
                      c.material_projection_version
           )
         ORDER BY c.external_id
        """,
        (
            tenant_id,
            NINJA_SOURCE_INSTANCE_ID,
            RETIRED_SNAPSHOT_SCOPE,
            NINJA_SOURCE_BINDING_ID,
            NINJA_SOURCE_BINDING_ID,
        ),
    )
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, values, strict=True)) for values in cur.fetchall()]


def _measure(
    cur: Any,
    *,
    tenant_id: int,
) -> tuple[StaleScopeResult, list[uuid.UUID]]:
    _assert_source_provenance(cur, tenant_id=tenant_id)
    rows = _target_rows(cur, tenant_id=tenant_id)
    evaluated = [(row, _blockers(row)) for row in rows]
    eligible = [row for row, blockers in evaluated if not any(blockers.values())]
    _, digest = observed_identity_summary(eligible)
    corrected = _already_corrected_rows(cur, tenant_id=tenant_id)
    _, corrected_digest = observed_identity_summary(corrected)
    blocked = sum(any(blockers.values()) for _, blockers in evaluated)
    result = StaleScopeResult(
        tenant_id=tenant_id,
        active_records=len(rows),
        eligible_records=len(eligible),
        eligible_identity_digest=digest.hex(),
        blocked_records=blocked,
        shape_blockers=sum(blockers["shape"] for _, blockers in evaluated),
        provenance_blockers=sum(blockers["provenance"] for _, blockers in evaluated),
        missing_legacy_device_blockers=sum(
            blockers["missing_legacy"] for _, blockers in evaluated
        ),
        current_legacy_device_blockers=sum(
            blockers["current_legacy"] for _, blockers in evaluated
        ),
        withdrawal_boundary_blockers=sum(
            blockers["boundary"] for _, blockers in evaluated
        ),
        open_history_blockers=sum(blockers["history"] for _, blockers in evaluated),
        already_corrected_records=len(corrected),
        already_corrected_identity_digest=corrected_digest.hex(),
        updated_current_rows=0,
        closed_history_rows=0,
        apply=False,
    )
    return result, [row["observation_id"] for row in eligible]


def measure(cur: Any, *, tenant_id: int) -> StaleScopeResult:
    result, _ = _measure(cur, tenant_id=tenant_id)
    return result


def _assert_pinned_selection(
    result: StaleScopeResult,
    *,
    expected_count: int,
    expected_digest: str,
) -> bool:
    if result.blocker_count:
        raise StaleScopeBlocked("stale-scope correction has eligibility blockers")
    if (
        result.eligible_records == 0
        and result.already_corrected_records == expected_count
        and result.already_corrected_identity_digest == expected_digest
    ):
        return False
    if (
        result.eligible_records != expected_count
        or result.eligible_identity_digest != expected_digest
    ):
        raise StaleScopeBlocked("stale-scope correction does not match approved target")
    return True


def process(
    cur: Any,
    *,
    tenant_id: int,
    apply: bool,
    expected_count: int | None = None,
    expected_digest: str | None = None,
) -> StaleScopeResult:
    measured, _ = _measure(cur, tenant_id=tenant_id)
    if not apply:
        return measured
    if expected_count is None or expected_digest is None:
        raise ValueError("apply requires expected_count and expected_digest")
    _assert_pinned_selection(
        measured,
        expected_count=expected_count,
        expected_digest=expected_digest,
    )
    cur.execute(
        """
        SELECT pg_advisory_xact_lock(
            hashtextextended(%s || '|' || %s || '|' || %s, 0)
        )
        """,
        (str(tenant_id), str(NINJA_SOURCE_INSTANCE_ID), RETIRED_SNAPSHOT_SCOPE),
    )
    locked_measurement, eligible_ids = _measure(cur, tenant_id=tenant_id)
    pending = _assert_pinned_selection(
        locked_measurement,
        expected_count=expected_count,
        expected_digest=expected_digest,
    )
    if not pending:
        return replace(locked_measurement, apply=True)
    if not eligible_ids:
        raise StaleScopeBlocked("stale-scope correction target is empty")
    cur.execute(
        """
        SELECT c.observation_id
          FROM operations.entity_observation_current c
          JOIN ninja_core.devices d ON d.id::text = c.external_id
         WHERE c.observation_id = ANY(%s)
         FOR UPDATE OF c, d
        """,
        (eligible_ids,),
    )
    if len(cur.fetchall()) != expected_count:
        raise StaleScopeBlocked("stale-scope correction lock selection changed")
    final_measurement, final_ids = _measure(cur, tenant_id=tenant_id)
    _assert_pinned_selection(
        final_measurement,
        expected_count=expected_count,
        expected_digest=expected_digest,
    )
    if set(final_ids) != set(eligible_ids):
        raise StaleScopeBlocked("stale-scope correction identity set changed")

    cur.execute(
        """
        UPDATE operations.entity_observation_current c
           SET active = FALSE,
               withdrawn_at = d.missing_since
          FROM ninja_core.devices d
         WHERE c.observation_id = ANY(%s)
           AND d.id::text = c.external_id
           AND c.tenant_id = %s
           AND c.source_instance_id = %s
           AND c.external_namespace = 'device'
           AND c.snapshot_scope = %s
           AND c.active IS TRUE
           AND c.withdrawn_at IS NULL
           AND d.is_current IS FALSE
           AND d.missing_since > GREATEST(c.observed_at, c.last_seen_at)
        """,
        (
            eligible_ids,
            tenant_id,
            NINJA_SOURCE_INSTANCE_ID,
            RETIRED_SNAPSHOT_SCOPE,
        ),
    )
    updated_current = cur.rowcount or 0
    cur.execute(
        """
        UPDATE operations.entity_observation_history h
           SET effective_to = c.withdrawn_at,
               last_seen_at = c.last_seen_at
          FROM operations.entity_observation_current c
         WHERE c.observation_id = ANY(%s)
           AND h.tenant_id = c.tenant_id
           AND h.source_instance_id = c.source_instance_id
           AND h.external_namespace = c.external_namespace
           AND h.parent_external_namespace = c.parent_external_namespace
           AND h.parent_external_id = c.parent_external_id
           AND h.external_id = c.external_id
           AND h.effective_to IS NULL
           AND h.active IS TRUE
           AND h.effective_from < c.withdrawn_at
           AND h.material_hash = c.material_hash
           AND h.material_projection_version = c.material_projection_version
        """,
        (eligible_ids,),
    )
    closed_history = cur.rowcount or 0
    if updated_current != expected_count or closed_history != expected_count:
        raise StaleScopeBlocked("stale-scope correction update was incomplete")
    return replace(
        locked_measurement,
        updated_current_rows=updated_current,
        closed_history_rows=closed_history,
        apply=True,
    )


def run(
    *,
    tenant_id: int = 1,
    apply: bool = False,
    expected_count: int | None = None,
    expected_digest: str | None = None,
) -> StaleScopeResult:
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")
    if apply:
        if expected_count is None or expected_count < 1:
            raise ValueError("apply requires a positive expected_count")
        if expected_digest is None or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            raise ValueError("apply requires a lowercase SHA-256 expected_digest")
    with db.transaction() as cur:
        if apply:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        else:
            cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(
            "SELECT set_config('operations.tenant_id', %s, TRUE)",
            (str(tenant_id),),
        )
        return process(
            cur,
            tenant_id=tenant_id,
            apply=apply,
            expected_count=expected_count,
            expected_digest=expected_digest,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure or withdraw retired Ninja scope evidence; defaults to "
            "read-only aggregate measurement"
        )
    )
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    if args.apply and (args.expected_count is None or args.expected_digest is None):
        parser.error("--apply requires --expected-count and --expected-digest")

    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    try:
        result = run(
            tenant_id=args.tenant_id,
            apply=args.apply,
            expected_count=args.expected_count,
            expected_digest=args.expected_digest,
        )
    except StaleScopeBlocked as exc:
        parser.exit(2, json.dumps({"error": str(exc)}, sort_keys=True) + "\n")
    except Exception:
        parser.exit(
            1,
            json.dumps(
                {"error": "stale-scope correction failed; no rows committed"},
                sort_keys=True,
            )
            + "\n",
        )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
