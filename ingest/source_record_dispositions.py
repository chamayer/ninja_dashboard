"""Disposition every association-reassessment row by class (user decision 2026-11-01).

Runs the reassessment preview under the live §5 policy and records one outcome
per row that does not re-attach the same way, so nothing waits for row-by-row
review:

* ``keep`` / ``no_matching_computer``: an attached record nothing else points
  to; continuity holds (design §5).
* ``keep`` / ``ambiguous``: several possibilities; a strong contradiction is
  raised by the standing identity rule, not here.
* ``move`` / ``matched_identity``: the shared matcher identifies one other
  Computer. Applied through ``set_source_association`` and undoable from the
  record page.
* ``move`` / ``unique_new_match``: an unattached record with exactly one
  policy-qualified match, attached the same way.

Run on the ingest container: ``python -m ingest.source_record_dispositions``.
"""

from __future__ import annotations

import collections
import json
import time
import uuid
from typing import Any

from ingest import db, source_record_reassessment
from ingest import preview_identity_reconciliation
from ingest.identity.matching import (
    OwnershipMatchDeferred,
    _identity_exclusions,
    _resolve_match,
    load_identity_match_policies,
    record_name_short,
)
from shared.identity_evidence import current_client_scopes


def classify(entry: dict[str, Any]) -> tuple[str, str] | None:
    """(outcome, class) for one preview entry, or None when nothing is recorded."""
    attached = entry["previous_device_id"] is not None
    outcome = entry["outcome"]
    if attached:
        if outcome == "same":
            return None
        if outcome == "unmatched":
            return "keep", "no_matching_computer"
        if outcome == "ambiguous":
            return "keep", "ambiguous"
        if outcome == "changed":
            if entry["matcher"] and len(entry["candidates"]) == 1:
                return "move", "matched_identity"
            return "keep", "ambiguous"
        return None
    if outcome == "newly_matched" and len(entry["candidates"]) == 1:
        return "move", "unique_new_match"
    return None


_REASONS = {
    "no_independent_evidence": "Kept: no other evidence points to this record; the "
    "existing attachment supplies continuity (design §5).",
    "no_matching_computer": "Kept: no other Computer matches this record.",
    "name_only_difference": "Kept: only a name suggests another Computer; a name "
    "cannot override an existing attachment.",
    "ambiguous": "Kept: several Computers are possible; a strong contradiction is "
    "raised by the identity rule.",
    "corroborated_hardware_match": "Moved: a corroborated serial or VM UUID points to "
    "exactly one other Computer.",
    "matched_identity": "Moved: the identity matcher selected one other Computer.",
    "unique_new_match": "Attached: exactly one Computer matches the identity policy.",
}


def _apply_move(cur: Any, tenant_id: int, entry: dict[str, Any]) -> bool:
    """Re-run the shared matcher and apply its current result."""
    rejected_serials = preview_identity_reconciliation._load_rejections(cur)
    cur.execute(
        """
        SELECT s.input_version, s.association_version, s.source_instance_id,
               s.external_namespace, s.parent_external_namespace,
               s.parent_external_id, s.external_id, o.observation_id,
               o.entity_type, o.platform, o.entity_key, o.canonical_data,
               operations.computer_client_independent_evidence(s.tenant_id, o.observation_id),
               o.active, o.device_id
          FROM operations.source_record_subjects s
          JOIN operations.entity_observation_current o
            ON o.tenant_id = s.tenant_id AND o.observation_id = s.observation_id
         WHERE s.tenant_id = %s AND s.id = %s
        """,
        (tenant_id, entry["subject_id"]),
    )
    row = cur.fetchone()
    if row is None or (row[0], row[1]) != (
        entry["input_version"],
        entry["association_version"],
    ):
        return False
    if not row[13] or (str(row[14]) if row[14] is not None else None) != entry["previous_device_id"]:
        return False
    origin_id = row[14]
    if origin_id is not None:
        target_id = uuid.UUID(str(entry["proposed_device_id"]))
        # An independently mapped source client can differ from the current
        # Computer's owner. Fence both owners before matcher and writer work.
        scopes = current_client_scopes(cur, tenant_id, [origin_id, target_id], lock=True)
        if scopes is None or scopes[origin_id] != scopes[target_id]:
            return False
    observation_id, entity_type, platform, entity_key, data, client_id = row[7:13]
    data = data or {}
    hostname = record_name_short(
        cur, platform, entity_type, data.get("hostname") or data.get("guest_name"), data.get("domain")
    )
    subject_id = uuid.UUID(str(entry["subject_id"]))
    excluded = _identity_exclusions(
        cur, tenant_id, [{"id": subject_id, "observation_id": observation_id}]
    )[subject_id]
    try:
        match = _resolve_match(
            cur, tenant_id=tenant_id, source_name=platform, external_id=entity_key,
            entity_type=entity_type, serial=data.get("serial_number"), vm_uuid=data.get("vm_uuid"),
            hostname=hostname or None, macs=data.get("macs") or [], client_id=client_id,
            policies=load_identity_match_policies(cur, tenant_id), is_online=data.get("is_online"),
            source_instance_id=row[2], skip_source_identity=True,
            identity_types=preview_identity_reconciliation._snapshot_identity_types(cur),
            excluded_observation_ids=excluded, trace=False,
            source_identity_key=tuple(row[3:7]),
            rejected_serials=rejected_serials,
        ).result
    except OwnershipMatchDeferred:
        return False
    if (match is None or len(match.candidates) != 1
            or str(match.device_id) != entry["proposed_device_id"]
            or match.matcher != entry["matcher"]):
        return False
    cur.execute(
        "SELECT entity_id, operations.lock_computer_client_scope(%s, id, client_id) "
        "FROM operations.devices WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
        (tenant_id, tenant_id, entry["proposed_device_id"]),
    )
    target = cur.fetchone()
    if target is None or target[0] is None or not target[1]:
        return False
    cur.execute(
        "SELECT operations.set_source_association(%s, %s, 'device', 'reassessment', 1,"
        " %s, %s, 'system', NULL, 'ingest.source_record_dispositions', %s::jsonb)",
        (
            entry["subject_id"],
            target[0],
            "reassessment " + ("move" if entry["previous_device_id"] else "attach"),
            row[1],
            json.dumps({
                "previous_device_id": entry["previous_device_id"],
                "matcher": match.matcher,
                "compared": match.compared,
            }),
        ),
    )
    return True


def run(tenant_id: int = 1, *, changes_only: bool = False) -> dict[str, Any]:
    report = source_record_reassessment.preview(tenant_id)
    run_id = uuid.uuid4()
    counts: collections.Counter = collections.Counter()
    for entry in report["entries"]:
        decided = classify(entry)
        if decided is None or entry["subject_id"] is None:
            continue
        outcome, klass = decided
        if changes_only and outcome != "move":
            continue
        with db.findings_transaction(tenant_id) as cur:
            applied = outcome == "move" and _apply_move(cur, tenant_id, entry)
            if outcome == "move" and not applied:
                outcome, klass = "keep", klass + "_inputs_changed"
            cur.execute(
                """
                INSERT INTO operations.source_record_dispositions (
                    tenant_id, run_id, subject_id, outcome, disposition_class, reason,
                    previous_device_id, proposed_device_id, applied, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (tenant_id, run_id, subject_id) DO NOTHING
                """,
                (
                    tenant_id,
                    run_id,
                    entry["subject_id"],
                    outcome,
                    klass,
                    _REASONS.get(
                        klass,
                        "Kept: the record changed after the preview; "
                        "it is assessed again by the standing rules.",
                    ),
                    entry["previous_device_id"],
                    entry["proposed_device_id"],
                    applied,
                    json.dumps(
                        {"matcher": entry["matcher"], "candidates": entry["candidates"],
                         "compared": entry["compared"],
                         "source_instance_id": entry["source_instance_id"],
                         "field_origin": entry["field_origin"]}
                    ),
                ),
            )
        counts[(outcome, klass)] += 1
    return {
        "run_id": str(run_id),
        "preview": report["summary"],
        "dispositions": {f"{o}:{k}": n for (o, k), n in sorted(counts.items())},
    }


def run_daily(tenant_id: int = 1) -> dict[str, Any]:
    """Reassess existing associations once daily from the identity Job."""
    with db.transaction() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        cur.execute(
            "SELECT operations.claim_maintenance(%s::bigint, %s::text, '1 day'::interval)",
            (tenant_id, "identity.reassessment"),
        )
        if not cur.fetchone()[0]:
            return {"ran": False}
    started = time.monotonic()
    result = run(tenant_id, changes_only=True)
    with db.transaction() as cur:
        cur.execute("SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),))
        cur.execute(
            "SELECT operations.complete_maintenance(%s::bigint, %s::text, %s::numeric)",
            (tenant_id, "identity.reassessment", round(time.monotonic() - started, 3)),
        )
    return {"ran": True, "preview": result["preview"], "dispositions": result["dispositions"]}


def main() -> None:
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=2)
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()
