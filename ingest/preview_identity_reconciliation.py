"""Produce a read-only, private preview of source-record reattachment.

This deliberately has no apply mode.  It asks the normal identity matcher how
each currently attached identity record would resolve if its own observation
were absent, then reports only deterministic proposed moves and review cases.
An operator must review a generated report before any separate apply plan.
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
from ingest.identity import identity_entity_types
from ingest.identity.matching import (
    MatchPreview,
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


def _attempts(preview: MatchPreview) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "matcher": attempt.matcher,
            "candidates": [str(device_id) for device_id in attempt.candidates],
            "usable": [str(device_id) for device_id in attempt.usable],
            "blockers": {str(device_id): reason for device_id, reason in attempt.blockers.items()},
        }
        for attempt in preview.attempts
    )


def _outcome(preview: MatchPreview, previous_device_id: UUID) -> tuple[str, UUID | None]:
    if preview.result is None:
        has_blocker = any(attempt.blockers for attempt in preview.attempts)
        return ("review_required" if has_blocker else "no_independent_match", None)
    if preview.result.device_id == previous_device_id:
        return "unchanged", previous_device_id
    # A non-unique result can be selected by recency during regular ingest, but
    # must never become an unattended historical correction.
    if len(preview.result.candidates) != 1:
        return "review_required", None
    return "proposed_reattachment", preview.result.device_id


def _report_digest(entries: list[PreviewEntry]) -> str:
    payload = json.dumps(
        [asdict(entry) for entry in entries], sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def run(*, tenant_id: int = 1) -> dict[str, Any]:
    """Build a reconciliation report inside one repeatable-read transaction."""
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        policies = load_identity_match_policies(cur, tenant_id)
        identity_types = sorted(identity_entity_types(cur))
        cur.execute(
            """
            SELECT observation_id, source_instance_id, external_namespace,
                   parent_external_namespace, parent_external_id, external_id,
                   device_id, active, entity_type, platform, entity_key, client_id,
                   canonical_data
              FROM operations.entity_observation_current
             WHERE tenant_id = %s AND device_id IS NOT NULL
               AND entity_type = ANY(%s::text[])
             ORDER BY observation_id
            """,
            (tenant_id, identity_types),
        )
        entries: list[PreviewEntry] = []
        for row in cur.fetchall():
            (
                observation_id, source_instance_id, external_namespace,
                parent_external_namespace, parent_external_id, external_id,
                previous_device_id, active, entity_type, platform, entity_key, client_id,
                canonical_data,
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
                identity_types=identity_types,
                excluded_observation_ids=(observation_id,),
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
                    candidates=tuple(str(device_id) for device_id in result.candidates) if result else (),
                    attempts=_attempts(preview),
                )
            )
    summary = {outcome: sum(entry.outcome == outcome for entry in entries) for outcome in (
        "unchanged", "proposed_reattachment", "review_required", "no_independent_match",
        "retained_evidence",
    )}
    return {
        "tenant_id": tenant_id,
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
    parser.add_argument("--output", type=Path, required=True, help="new private JSON path outside this repository")
    args = parser.parse_args()
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=1)
    report = run(tenant_id=args.tenant_id)
    write_report(report, args.output)
    print(json.dumps({key: report[key] for key in ("tenant_id", "entry_count", "digest", "summary")}, sort_keys=True))


if __name__ == "__main__":
    main()
