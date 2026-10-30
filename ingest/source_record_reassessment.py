"""One-time reassessment of existing associations (PLAN-004 R4, design §2.2).

Preview -> review -> apply; never clears associations first. Preserves canonical
IDs, explicit attachments and separations, source-group mappings, history and
decisions.

* ``preview`` (read-only, one repeatable-read snapshot) classifies every
  Computer-role record. Attached records are matched counterfactually without
  their own evidence (``preview_identity_reconciliation``); unattached present
  records are matched as they stand. Outcomes: ``same``, ``changed``,
  ``ambiguous``, ``unmatched``, ``newly_matched``, with old and proposed targets,
  matchers, candidates and the subject versions they were computed from.
* ``apply`` applies only what the reviewed policy covers: ``newly_matched`` rows
  with exactly one candidate, through ``associate_record`` with the existing
  association kept, and only while the subject's input and association versions
  are still those of the preview. A changed row returns to review. ``same`` needs
  no change. ``changed``, ``ambiguous`` and ``unmatched`` are written to the
  review list and never applied here.
* The report keeps the rollback mapping (each applied subject and the link it
  created) and is written outside the repository; it names private source
  identities.

Run on the production ingest container: ``python -m ingest.source_record_reassessment
--output /tmp/<new file>.json``.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from ingest import db, preview_identity_reconciliation
from ingest.identity import identity_entity_types
from ingest.identity.matching import (
    load_identity_match_policies,
    preview_match,
    record_name_short,
)

_ATTACHED_OUTCOMES = {
    "unchanged": "same",
    "retained_evidence": "same",
    "proposed_reattachment": "changed",
    "review_required": "ambiguous",
    "no_independent_match": "unmatched",
}


def _unattached(
    cur: Any, tenant_id: int, identity_types: list[str]
) -> list[dict[str, Any]]:
    policies = load_identity_match_policies(cur, tenant_id)
    cur.execute(
        """
        SELECT o.observation_id, o.entity_type, o.platform, o.entity_key, o.client_id,
               o.canonical_data, s.id, s.input_version, s.association_version
          FROM operations.entity_observation_current o
          JOIN operations.source_record_subjects s
            ON s.tenant_id = o.tenant_id AND s.observation_id = o.observation_id
         WHERE o.tenant_id = %s AND o.device_id IS NULL AND o.active
           AND o.entity_type = ANY(%s::text[])
         ORDER BY o.observation_id
        """,
        (tenant_id, identity_types),
    )
    entries = []
    for (
        observation_id,
        entity_type,
        platform,
        entity_key,
        client_id,
        data,
        subject_id,
        input_version,
        association_version,
    ) in cur.fetchall():
        data = data or {}
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
        result = preview.result
        if result is None:
            has_blocker = any(attempt.blockers for attempt in preview.attempts)
            outcome, proposed = ("ambiguous" if has_blocker else "unmatched"), None
        elif len(result.candidates) == 1:
            outcome, proposed = "newly_matched", result.device_id
        else:
            outcome, proposed = "ambiguous", None
        entries.append(
            {
                "subject_id": str(subject_id),
                "observation_id": str(observation_id),
                "entity_type": entity_type,
                "platform": platform,
                "previous_device_id": None,
                "outcome": outcome,
                "proposed_device_id": str(proposed) if proposed else None,
                "matcher": result.matcher if result else None,
                "candidates": [str(c) for c in result.candidates] if result else [],
                "input_version": input_version,
                "association_version": association_version,
            }
        )
    return entries


def preview(tenant_id: int = 1) -> dict[str, Any]:
    attached = preview_identity_reconciliation.run(tenant_id=tenant_id)
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute(
            "SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),)
        )
        identity_types = sorted(identity_entity_types(cur))
        cur.execute(
            """
            SELECT observation_id::text, id::text, input_version, association_version
              FROM operations.source_record_subjects WHERE tenant_id = %s
            """,
            (tenant_id,),
        )
        subjects = {row[0]: row[1:] for row in cur.fetchall()}
        unattached = _unattached(cur, tenant_id, identity_types)
    entries = []
    for entry in attached["entries"]:
        subject = subjects.get(entry["observation_id"])
        entries.append(
            {
                "subject_id": subject[0] if subject else None,
                "observation_id": entry["observation_id"],
                "entity_type": entry["entity_type"],
                "platform": entry["platform"],
                "previous_device_id": entry["previous_device_id"],
                "outcome": _ATTACHED_OUTCOMES[entry["outcome"]],
                "proposed_device_id": entry["proposed_device_id"],
                "matcher": entry["matcher"],
                "candidates": list(entry["candidates"]),
                "input_version": subject[1] if subject else None,
                "association_version": subject[2] if subject else None,
            }
        )
    entries.extend(unattached)
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["outcome"]] = summary.get(entry["outcome"], 0) + 1
    return {"tenant_id": tenant_id, "summary": summary, "entries": entries}


def apply(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the policy-covered rows that are still current; nothing else."""
    tenant_id = report["tenant_id"]
    applied, returned = [], []
    for entry in report["entries"]:
        if entry["outcome"] != "newly_matched" or len(entry["candidates"]) != 1:
            continue
        with db.transaction() as cur:
            cur.execute(
                "SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),)
            )
            cur.execute(
                """
                SELECT s.input_version, s.association_version, s.source_instance_id,
                       s.external_namespace, s.parent_external_namespace,
                       s.parent_external_id, s.external_id
                  FROM operations.source_record_subjects s
                 WHERE s.tenant_id = %s AND s.id = %s FOR UPDATE
                """,
                (tenant_id, entry["subject_id"]),
            )
            row = cur.fetchone()
            if row is None or (row[0], row[1]) != (
                entry["input_version"],
                entry["association_version"],
            ):
                returned.append(
                    {**entry, "returned_reason": "inputs changed since preview"}
                )
                continue
            cur.execute(
                "SELECT operations.associate_record(%s, %s, %s, %s, %s, %s, %s,"
                " 'reassessment', 'ingest.source_record_reassessment', true)",
                (tenant_id, *row[2:], entry["proposed_device_id"]),
            )
            if not cur.fetchone()[0]:
                returned.append({**entry, "returned_reason": "already associated"})
                continue
            cur.execute(
                "SELECT id FROM operations.entity_source_links"
                " WHERE tenant_id = %s AND source_subject_id = %s",
                (tenant_id, entry["subject_id"]),
            )
            applied.append(
                {
                    "subject_id": entry["subject_id"],
                    "device_id": entry["proposed_device_id"],
                    "link_id": str(cur.fetchone()[0]),
                    "rollback": "clear this association with set_source_association(p_entity => NULL)",
                }
            )
    review = [
        e
        for e in report["entries"]
        if e["outcome"] in ("changed", "ambiguous", "unmatched")
    ]
    return {
        "tenant_id": tenant_id,
        "preview_summary": report["summary"],
        "applied": applied,
        "returned_to_review": returned,
        "review_required": review,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    target = path.resolve()
    if target.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError(
            "output must be outside the repository; it names private source identities"
        )
    with target.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time association reassessment")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args()
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=2)
    report = preview(args.tenant_id)
    result = report if args.preview_only else {**apply(report), "preview": report}
    _write(args.output, result)
    counts = {
        "preview": report["summary"],
        "applied": len(result.get("applied", [])),
        "returned_to_review": len(result.get("returned_to_review", [])),
        "review_required": len(result.get("review_required", [])),
        "run_id": str(uuid.uuid4()),
    }
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
