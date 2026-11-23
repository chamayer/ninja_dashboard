"""Produce a read-only, private preview of source-record reattachment.

This deliberately has no apply mode. The default report assesses attached
records without their own observations. Universal mode also includes unattached
records and assesses serial and VM UUID matches across clients. An operator must
review a generated report before any separate apply plan; a machine match does
not establish whether an association change is permitted by the ownership contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ingest import db
from ingest.identity.matching import (
    MatchPreview,
    _identity_exclusions,
    load_identity_match_policies,
    preview_match,
    record_name_short,
)


@dataclass(frozen=True)
class PreviewEntry:
    observation_id: str
    source_instance_id: str
    external_namespace: str | None
    parent_external_namespace: str | None
    parent_external_id: str | None
    external_id: str | None
    entity_type: str
    platform: str
    previous_device_id: str
    outcome: str
    proposed_device_id: str | None
    matcher: str | None
    candidates: tuple[str, ...]
    attempts: tuple[dict[str, Any], ...]
    compared: dict[str, Any]
    ownership_deferred: bool = False


def _attempts(preview: MatchPreview) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "matcher": attempt.matcher,
            "candidates": [str(device_id) for device_id in attempt.candidates],
            "usable": [str(device_id) for device_id in attempt.usable],
            "blockers": {str(device_id): reason for device_id, reason in attempt.blockers.items()},
            "missing": list(attempt.missing),
        }
        for attempt in preview.attempts
    )


def _outcome(preview: MatchPreview, previous_device_id: UUID) -> tuple[str, UUID | None]:
    if preview.result is None:
        has_blocker = preview.ownership_deferred or any(
            attempt.blockers or attempt.missing or len(attempt.usable) > 1 for attempt in preview.attempts
        )
        return ("review_required" if has_blocker else "no_independent_match", None)
    if preview.result.device_id == previous_device_id:
        return "unchanged", previous_device_id
    # Guard against a future matcher returning a non-unique selection.
    if len(preview.result.candidates) != 1:
        return "review_required", None
    return "proposed_reattachment", preview.result.device_id


def _report_digest(entries: list[PreviewEntry]) -> str:
    payload = json.dumps(
        [asdict(entry) for entry in entries], sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def run(*, tenant_id: int = 1, universal: bool = False) -> dict[str, Any]:
    """Build a reconciliation report inside one repeatable-read transaction."""
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")
    if universal:
        from ingest import source_record_reassessment

        report = source_record_reassessment.preview(tenant_id, universal=True)
        report["universal"] = True
        report["entry_count"] = len(report["entries"])
        report["digest"] = source_record_reassessment._report_digest(report)
        return report
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        return _run_in_snapshot(cur, tenant_id, universal=universal)


def _snapshot_identity_types(cur: Any) -> list[str]:
    cur.execute("SELECT name FROM operations.entity_types WHERE is_identity_signal ORDER BY name")
    types = [row[0] for row in cur.fetchall()]
    if not types:
        raise RuntimeError("identity signal types are unavailable")
    return types


def _load_rejections(cur: Any) -> frozenset[str]:
    cur.execute(
        "SELECT normalized_value FROM operations.identity_value_rejections "
        "WHERE value_kind = 'serial' AND enabled"
    )
    return frozenset(row[0] for row in cur.fetchall())


def _run_in_snapshot(
    cur: Any, tenant_id: int, *, subject_ids: list[UUID] | None = None,
    universal: bool = False, assess_globally: bool = False,
) -> dict[str, Any]:
    """Build a report using the caller's existing tenant-scoped snapshot."""
    rejected_serials = _load_rejections(cur)
    policies = load_identity_match_policies(cur, tenant_id)
    identity_types = _snapshot_identity_types(cur)
    cur.execute(
        """
        SELECT eo.observation_id, eo.source_instance_id, eo.external_namespace,
               eo.parent_external_namespace, eo.parent_external_id, eo.external_id,
               eo.device_id, eo.active, eo.entity_type, eo.platform, eo.entity_key,
               operations.computer_client_independent_evidence(eo.tenant_id, eo.observation_id),
               eo.canonical_data, subject.id
          FROM operations.entity_observation_current eo
          LEFT JOIN operations.source_record_subjects subject
            ON subject.tenant_id = eo.tenant_id AND subject.subject_kind = 'record'
           AND subject.source_instance_id = eo.source_instance_id
           AND subject.external_namespace = eo.external_namespace
           AND subject.parent_external_namespace = eo.parent_external_namespace
           AND subject.parent_external_id = eo.parent_external_id
           AND subject.external_id = eo.external_id
         WHERE eo.tenant_id = %s AND eo.device_id IS NOT NULL
           AND eo.entity_type = ANY(%s::text[])
           AND (%s::uuid[] IS NULL OR subject.id = ANY(%s::uuid[]))
           -- Ninja's device-health companions carry no identity fields; the
           -- matcher skips them, so previewing them only yields noise.
           AND eo.external_namespace <> 'device-health'
         ORDER BY eo.observation_id
        """,
        (tenant_id, identity_types, subject_ids, subject_ids),
    )
    rows = cur.fetchall()
    exclusions = _identity_exclusions(
        cur, tenant_id, [{"id": row[13], "observation_id": row[0]} for row in rows if row[13]]
    )
    entries: list[PreviewEntry] = []
    for row in rows:
        (
            observation_id, source_instance_id, external_namespace,
            parent_external_namespace, parent_external_id, external_id,
            previous_device_id, active, entity_type, platform, entity_key, client_id,
            canonical_data, subject_id,
        ) = row
        data = canonical_data or {}
        if not active:
            entries.append(
                PreviewEntry(
                    observation_id=str(observation_id),
                    source_instance_id=str(source_instance_id),
                    external_namespace=external_namespace,
                    parent_external_namespace=parent_external_namespace,
                    parent_external_id=parent_external_id,
                    external_id=external_id,
                    entity_type=entity_type,
                    platform=platform,
                    previous_device_id=str(previous_device_id),
                    outcome="retained_evidence",
                    proposed_device_id=None,
                    matcher=None,
                    candidates=(),
                    attempts=(),
                    compared={},
                )
            )
            continue
        if not external_id or subject_id is None:
            entries.append(
                PreviewEntry(
                    observation_id=str(observation_id),
                    source_instance_id=str(source_instance_id),
                    external_namespace=external_namespace,
                    parent_external_namespace=parent_external_namespace,
                    parent_external_id=parent_external_id,
                    external_id=external_id,
                    entity_type=entity_type,
                    platform=platform,
                    previous_device_id=str(previous_device_id),
                    outcome="review_required",
                    proposed_device_id=None,
                    matcher=None,
                    candidates=(),
                    attempts=(),
                    compared={},
                )
            )
            continue
        hostname = record_name_short(
            cur,
            platform,
            entity_type,
            data.get("hostname") or data.get("guest_name"),
            data.get("domain"),
        )
        preview = preview_match(
            cur,
            tenant_id=tenant_id,
            source_name=platform,
            external_id=entity_key,
            entity_type=entity_type,
            serial=data.get("serial_number"),
            vm_uuid=data.get("vm_uuid"),
            hostname=hostname or None,
            macs=data.get("macs") or [],
            client_id=client_id,
            policies=policies,
            is_online=data.get("is_online"),
            source_instance_id=source_instance_id,
            identity_types=identity_types,
            excluded_observation_ids=exclusions[subject_id],
            source_identity_key=(external_namespace, parent_external_namespace,
                                 parent_external_id, external_id),
            rejected_serials=rejected_serials,
            universal=universal,
            assess_globally=assess_globally,
        )
        outcome, proposed_device_id = _outcome(preview, previous_device_id)
        result = preview.result
        entries.append(
            PreviewEntry(
                observation_id=str(observation_id),
                source_instance_id=str(source_instance_id),
                external_namespace=external_namespace,
                parent_external_namespace=parent_external_namespace,
                parent_external_id=parent_external_id,
                external_id=external_id,
                entity_type=entity_type,
                platform=platform,
                previous_device_id=str(previous_device_id),
                outcome=outcome,
                proposed_device_id=str(proposed_device_id) if proposed_device_id else None,
                matcher=result.matcher if result else None,
                candidates=(
                    tuple(str(device_id) for device_id in result.candidates) if result else
                    tuple(sorted({str(device_id) for attempt in preview.attempts
                                  for device_id in attempt.candidates}))
                ),
                attempts=_attempts(preview),
                compared=result.compared if result else {},
                ownership_deferred=preview.ownership_deferred,
            )
        )
    summary = {outcome: sum(entry.outcome == outcome for entry in entries) for outcome in (
        "unchanged", "proposed_reattachment", "review_required", "no_independent_match",
        "retained_evidence",
    )}
    return {
        "tenant_id": tenant_id,
        "universal": universal,
        "entry_count": len(entries),
        "digest": _report_digest(entries),
        "summary": summary,
        "entries": [asdict(entry) for entry in entries],
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    """Write the sensitive report outside the repository without overwriting it."""
    target = output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if target.is_relative_to(repository):
        raise ValueError("output must be outside the repository; it may contain private source identities")
    if not target.parent.is_dir():
        raise ValueError("output parent directory does not exist")
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview identity reattachment without changing data")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--universal", action="store_true", help="assess hardware matches across clients")
    parser.add_argument("--output", type=Path, required=True, help="new private JSON path outside this repository")
    args = parser.parse_args()
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    report = run(tenant_id=args.tenant_id, universal=args.universal)
    write_report(report, args.output)
    print(json.dumps({key: report[key] for key in ("tenant_id", "entry_count", "digest", "summary")}, sort_keys=True))


if __name__ == "__main__":
    main()
