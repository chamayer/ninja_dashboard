"""Backfill compact Ninja daily device-presence rollups.

This operator-invoked tool is deliberately separate from startup migrations.
It processes one completed UTC day per transaction, defaults to read-only
measurement, and is safe to rerun because daily rows use conflict-to-no-op.
Only aggregate counts are returned or printed.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ingest import db


@dataclass(frozen=True)
class DayResult:
    rollup_day: date
    legacy_devices: int
    matched_devices: int
    unmatched_devices: int
    ambiguous_devices: int
    inserted_rows: int
    apply: bool


def _measure_day(cur: Any, *, tenant_id: int, rollup_day: date) -> DayResult:
    day_start, day_end = _utc_bounds(rollup_day)
    cur.execute(
        """
        WITH legacy_devices AS (
            SELECT DISTINCT s.device_id
              FROM ninja_core.device_snapshots s
             WHERE s.snapshot_at >= %s
               AND s.snapshot_at < %s
        ), mappings AS (
            SELECT l.device_id, COUNT(c.observation_id) AS match_count
              FROM legacy_devices l
              LEFT JOIN operations.entity_observation_current c
                ON c.tenant_id = %s
               AND lower(c.platform) = 'ninja'
               AND c.external_namespace = 'device'
               AND c.external_id = l.device_id::text
             GROUP BY l.device_id
        )
        SELECT COUNT(*)::bigint,
               COUNT(*) FILTER (WHERE match_count = 1)::bigint,
               COUNT(*) FILTER (WHERE match_count = 0)::bigint,
               COUNT(*) FILTER (WHERE match_count > 1)::bigint
          FROM mappings
        """,
        (day_start, day_end, tenant_id),
    )
    legacy, matched, unmatched, ambiguous = cur.fetchone()
    return DayResult(
        rollup_day=rollup_day,
        legacy_devices=legacy,
        matched_devices=matched,
        unmatched_devices=unmatched,
        ambiguous_devices=ambiguous,
        inserted_rows=0,
        apply=False,
    )


def _insert_day(cur: Any, *, tenant_id: int, rollup_day: date) -> int:
    day_start, day_end = _utc_bounds(rollup_day)
    cur.execute(
        """
        WITH legacy_devices AS (
            SELECT DISTINCT s.device_id
              FROM ninja_core.device_snapshots s
             WHERE s.snapshot_at >= %s
               AND s.snapshot_at < %s
        ), mappings AS (
            SELECT %s::bigint AS tenant_id,
                   (array_agg(c.observation_id))[1] AS observation_id,
                   'device'::varchar(120) AS external_namespace
              FROM legacy_devices l
              JOIN operations.entity_observation_current c
                ON c.tenant_id = %s
               AND lower(c.platform) = 'ninja'
               AND c.external_namespace = 'device'
               AND c.external_id = l.device_id::text
             GROUP BY l.device_id
             HAVING COUNT(c.observation_id) = 1
        )
        INSERT INTO operations.source_record_seen_daily
          (tenant_id, source_record_id, external_namespace, rollup_day,
           first_snapshot_run_id, backfilled_from_legacy)
        SELECT tenant_id, observation_id, external_namespace, %s, NULL, TRUE
          FROM mappings
        ON CONFLICT (tenant_id, source_record_id, rollup_day) DO NOTHING
        """,
        (day_start, day_end, tenant_id, tenant_id, rollup_day),
    )
    return cur.rowcount


def process_day(
    cur: Any,
    *,
    tenant_id: int,
    rollup_day: date,
    apply: bool,
) -> DayResult:
    """Measure one day and optionally insert only fully mapped results."""
    measured = _measure_day(cur, tenant_id=tenant_id, rollup_day=rollup_day)
    if not apply:
        return measured
    if measured.unmatched_devices or measured.ambiguous_devices:
        raise RuntimeError(
            "daily rollup mapping is incomplete: "
            f"unmatched={measured.unmatched_devices}, "
            f"ambiguous={measured.ambiguous_devices}"
        )
    inserted = _insert_day(cur, tenant_id=tenant_id, rollup_day=rollup_day)
    return DayResult(
        **{
            **asdict(measured),
            "inserted_rows": inserted,
            "apply": True,
        }
    )


def _utc_bounds(rollup_day: date) -> tuple[datetime, datetime]:
    day_start = datetime(
        rollup_day.year,
        rollup_day.month,
        rollup_day.day,
        tzinfo=timezone.utc,
    )
    return day_start, day_start + timedelta(days=1)


def run(
    *,
    start_day: date,
    end_day: date,
    tenant_id: int = 1,
    apply: bool = False,
) -> list[DayResult]:
    """Process an inclusive range of completed UTC days."""
    if start_day > end_day:
        raise ValueError("start_day must be on or before end_day")
    if end_day >= datetime.now(timezone.utc).date():
        raise ValueError("end_day must be a completed UTC day")
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")

    results: list[DayResult] = []
    current_day = start_day
    while current_day <= end_day:
        with db.transaction() as cur:
            if apply:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            else:
                cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(
                "SELECT set_config('operations.tenant_id', %s, TRUE)",
                (str(tenant_id),),
            )
            result = process_day(
                cur,
                tenant_id=tenant_id,
                rollup_day=current_day,
                apply=apply,
            )
        results.append(result)
        print(json.dumps(_json_result(result), sort_keys=True))
        current_day += timedelta(days=1)
    return results


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _json_result(result: DayResult) -> dict[str, Any]:
    return {**asdict(result), "rollup_day": result.rollup_day.isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure or backfill Ninja daily device presence; defaults to "
            "read-only measurement"
        )
    )
    parser.add_argument("--start-day", type=_date, required=True)
    parser.add_argument("--end-day", type=_date, required=True)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="insert mapped rollups; omit for read-only measurement",
    )
    args = parser.parse_args()

    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    results = run(**vars(args))
    print(
        json.dumps(
            {
                "apply": args.apply,
                "days_completed": len(results),
                "legacy_devices": sum(r.legacy_devices for r in results),
                "matched_devices": sum(r.matched_devices for r in results),
                "inserted_rows": sum(r.inserted_rows for r in results),
                "unmatched_devices": sum(r.unmatched_devices for r in results),
                "ambiguous_devices": sum(r.ambiguous_devices for r in results),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
