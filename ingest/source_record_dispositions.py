"""Disposition every association-reassessment row by class (user decision 2026-11-01).

Runs the reassessment preview under the live §5 policy and records one outcome
per row that does not re-attach the same way, so nothing waits for row-by-row
review:

* ``keep`` / ``no_independent_evidence``: an attached record nothing else points
  to; continuity holds (design §5).
* ``keep`` / ``name_only_difference``: a name suggests another Computer but no
  corroborated serial/VM UUID does; a name cannot override continuity.
* ``keep`` / ``ambiguous``: several possibilities; a strong contradiction is
  raised by the standing identity rule, not here.
* ``move`` / ``corroborated_hardware_match``: a corroborated serial/VM UUID points
  to exactly one other Computer. Applied through ``set_source_association`` while
  the record is unchanged since the preview; undoable from the record page.
* ``move`` / ``unique_new_match``: an unattached record with exactly one
  corroborated match, attached the same way.

Run on the ingest container: ``python -m ingest.source_record_dispositions``.
"""

from __future__ import annotations

import collections
import json
import uuid
from typing import Any

from ingest import db, source_record_reassessment

_STRONG = ("serial", "vm_uuid")


def classify(entry: dict[str, Any]) -> tuple[str, str] | None:
    """(outcome, class) for one preview entry, or None when nothing is recorded."""
    attached = entry["previous_device_id"] is not None
    outcome = entry["outcome"]
    if attached:
        if outcome == "same":
            return None
        if outcome == "unmatched":
            return "keep", "no_independent_evidence"
        if outcome == "ambiguous":
            return "keep", "ambiguous"
        if outcome == "changed":
            if entry["matcher"] in _STRONG and len(entry["candidates"]) == 1:
                return "move", "corroborated_hardware_match"
            return "keep", "name_only_difference"
        return None
    if outcome == "newly_matched" and len(entry["candidates"]) == 1:
        return "move", "unique_new_match"
    return None


_REASONS = {
    "no_independent_evidence": "Kept: no other evidence points to this record; the "
    "existing attachment supplies continuity (design §5).",
    "name_only_difference": "Kept: only a name suggests another Computer; a name "
    "cannot override an existing attachment.",
    "ambiguous": "Kept: several Computers are possible; a strong contradiction is "
    "raised by the identity rule.",
    "corroborated_hardware_match": "Moved: a corroborated serial or VM UUID points to "
    "exactly one other Computer.",
    "unique_new_match": "Attached: exactly one corroborated Computer matches.",
}


def _apply_move(cur: Any, tenant_id: int, entry: dict[str, Any]) -> bool:
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
        return False
    cur.execute(
        "SELECT entity_id FROM operations.devices"
        " WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
        (tenant_id, entry["proposed_device_id"]),
    )
    target = cur.fetchone()
    if target is None:
        return False
    cur.execute(
        "SELECT operations.set_source_association(%s, %s, 'device', 'reassessment', 1,"
        " %s, %s, 'system', NULL, 'ingest.source_record_dispositions', %s::jsonb)",
        (
            entry["subject_id"],
            target[0],
            "reassessment " + ("move" if entry["previous_device_id"] else "attach"),
            row[1],
            json.dumps({"previous_device_id": entry["previous_device_id"]}),
        ),
    )
    return True


def run(tenant_id: int = 1) -> dict[str, Any]:
    report = source_record_reassessment.preview(tenant_id)
    run_id = uuid.uuid4()
    counts: collections.Counter = collections.Counter()
    for entry in report["entries"]:
        decided = classify(entry)
        if decided is None or entry["subject_id"] is None:
            continue
        outcome, klass = decided
        with db.transaction() as cur:
            cur.execute(
                "SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),)
            )
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
                        {"matcher": entry["matcher"], "candidates": entry["candidates"]}
                    ),
                ),
            )
        counts[(outcome, klass)] += 1
    return {
        "run_id": str(run_id),
        "preview": report["summary"],
        "dispositions": {f"{o}:{k}": n for (o, k), n in sorted(counts.items())},
    }


def main() -> None:
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=2)
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()
