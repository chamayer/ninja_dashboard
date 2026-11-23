"""Preview or apply a reviewed Ninja successor on one Computer."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ingest import db, device_status_settings
from ingest.normalize import normalize_mac, parse_dt
from ingest.preview_identity_reconciliation import _load_rejections
from shared.findings_contract import guard_findings_writes
from shared.identity_evidence import assess_identifier_group, current_client_scopes, usable_serial

_PROCESS = "ingest.ninja_record_supersession"


class SuccessorNeedsReview(ValueError):
    """The current evidence does not support replacing the Ninja association."""


def _plan(
    cur, tenant_id: int, computer_id: UUID, candidate_id: UUID | None, *, estimated_id: UUID | None = None
) -> dict:
    """Read the whole group and choose only a proven, unambiguous successor."""
    cur.execute(
        """
        SELECT s.id, s.input_version, s.association_version, eo.device_id, eo.active,
               eo.entity_key, eo.canonical_data,
               operations.computer_client_independent_evidence(s.tenant_id, s.observation_id),
               operations.ninja_record_excluded_from_computer(s.tenant_id, %s, eo.entity_key),
               EXISTS (
                   SELECT 1 FROM operations.entity_source_link_history history
                    WHERE history.tenant_id = s.tenant_id AND history.source_instance_id = s.source_instance_id
                      AND history.external_namespace = s.external_namespace
                      AND history.parent_external_namespace = s.parent_external_namespace
                      AND history.parent_external_id = s.parent_external_id
                      AND history.external_id = s.external_id AND history.effective_to IS NULL
                      AND history.actor_kind IN ('operator', 'user')
               )
          FROM operations.source_record_subjects s
          JOIN operations.entity_observation_current eo
            ON eo.tenant_id = s.tenant_id AND eo.observation_id = s.observation_id
         WHERE s.tenant_id = %s AND s.subject_kind = 'record' AND eo.platform = 'Ninja'
           AND (eo.device_id IN (%s, %s) OR (s.id = %s AND eo.device_id IS NULL AND eo.active))
           AND NOT operations.is_companion_stream(s.tenant_id, s.source_instance_id, s.external_namespace)
           AND NOT operations.ninja_record_is_superseded(
               s.tenant_id, s.source_instance_id, s.external_namespace,
               s.parent_external_namespace, s.parent_external_id, s.external_id)
         ORDER BY s.id
        """,
        (computer_id, tenant_id, computer_id, estimated_id, candidate_id),
    )
    rows = cur.fetchall()
    if len(rows) < 2 or (candidate_id is not None and all(row[0] != candidate_id for row in rows)):
        raise SuccessorNeedsReview("Review requires at least two Ninja records on the Computer or a supplied candidate")
    if any(row[8] or row[9] for row in rows):
        raise SuccessorNeedsReview("An explicit identity decision requires review")
    if estimated_id is not None:
        scopes = current_client_scopes(cur, tenant_id, [computer_id, estimated_id], lock=True)
        if (
            len(rows) != 2 or {row[3] for row in rows} != {computer_id, estimated_id}
            or not scopes or scopes[computer_id] != scopes[estimated_id]
            or any(row[7] != scopes[computer_id] for row in rows)
        ):
            raise SuccessorNeedsReview("The two Ninja assignments need independent client evidence")

    rejected = _load_rejections(cur)
    cutoff = datetime.now(UTC) - timedelta(
        days=device_status_settings.device_offline_days(cur, tenant_id, computer_id)
    )
    records = []
    for subject_id, inputs, association, device_id, active, _, data, client_id, _, _ in rows:
        data = data or {}
        serial = data.get("serial_number")
        contact = parse_dt(data.get("last_contact_at"))
        if contact is not None and contact.utcoffset() is None:
            contact = None
        offline = not active or data.get("is_online") is False or data.get("offline") is True
        macs = data.get("macs")
        records.append({
            "subject_id": str(subject_id), "input_version": inputs, "association_version": association,
            "device_id": str(device_id) if device_id else None, "client_id": str(client_id) if client_id else None,
            "contact": contact, "offline": offline,
            "recent": active and contact is not None and contact >= cutoff,
            "serial": serial.strip().lower() if usable_serial(serial, rejected) else None,
            "macs": {
                normalized
                for value in (macs if isinstance(macs, list) else ())
                if isinstance(value, str) and (normalized := normalize_mac(value))
            },
        })
    # Historical Ninja vm_uuid values were node IDs. Use qualified BIOS serial
    # evidence for this bounded repair without treating those IDs as hardware.
    assessment = assess_identifier_group(
        serial_groups=[(record["serial"],) for record in records], vm_uuid_groups=[],
    )
    if assessment.outcome != "same":
        raise SuccessorNeedsReview(f"Shared identity assessment returned {assessment.reason}. Review the group.")
    current = [record for record in records if record["recent"] and not record["offline"]]
    if not current:
        current = [record for record in records if record["recent"]]
    if (
        len(current) != 1
        or any(not record["offline"] or record["contact"] is None
               or record["contact"] >= current[0]["contact"]
               for record in records if record is not current[0])
    ):
        raise SuccessorNeedsReview("Agent contact does not establish one current Ninja record. Review the group.")
    successor = current[0]
    if any(not record["macs"] & successor["macs"] for record in records if record is not successor):
        raise SuccessorNeedsReview("A shared serial needs matching hardware address evidence.")
    if successor["device_id"] is None:
        scopes = current_client_scopes(cur, tenant_id, [computer_id], lock=False)
        if not scopes or str(scopes[computer_id]) != successor["client_id"]:
            raise SuccessorNeedsReview("Unattached Ninja successor does not match the Computer's current scope")
    for record in records:
        record.pop("serial")
        record.pop("macs")
    return {
        "tenant_id": tenant_id, "computer_id": str(computer_id),
        "machine_outcome": assessment.outcome, "machine_reason": assessment.reason,
        "selected_subject_id": successor["subject_id"], "records": records,
        "estimated_id": str(estimated_id) if estimated_id else None,
    }


def _digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, default=str).encode()).hexdigest()


def plan_matched_successor(cur, tenant_id: int, computer_id: UUID, candidate_id: UUID) -> dict | None:
    """Return a plan only if the incoming record is the clear successor."""
    try:
        plan = _plan(cur, tenant_id, computer_id, candidate_id)
    except SuccessorNeedsReview:
        return None
    return plan if plan["selected_subject_id"] == str(candidate_id) else None


def replace_matched_ninja_record(cur, tenant_id: int, computer_id: UUID, candidate_id: UUID) -> bool:
    """Apply a clear successor within the resolver's guarded transaction."""
    plan = plan_matched_successor(cur, tenant_id, computer_id, candidate_id)
    if plan is None:
        return False
    _apply(cur, tenant_id, computer_id, plan, _digest(plan))
    return True


def reconcile_existing_ninja_records(cur, tenant_id: int, computer_id: UUID) -> bool:
    """Retire the offline links of a legacy Computer with a clear successor."""
    try:
        plan = _plan(cur, tenant_id, computer_id, None)
    except SuccessorNeedsReview:
        return False
    _apply(cur, tenant_id, computer_id, plan, _digest(plan))
    return True


def prepare_estimated_ninja_merge(cur, tenant_id: int, computer_id: UUID, estimated_id: UUID) -> bool:
    """Close the proven predecessor before the caller merges the two anchors."""
    try:
        plan = _plan(cur, tenant_id, computer_id, None, estimated_id=estimated_id)
    except SuccessorNeedsReview:
        return False
    _apply(cur, tenant_id, computer_id, plan, _digest(plan))
    return True


def _apply(cur, tenant_id: int, computer_id: UUID, plan: dict, digest: str) -> dict:
    selected = next(row for row in plan["records"] if row["subject_id"] == plan["selected_subject_id"])
    for older in plan["records"]:
        if older is selected:
            continue
        evidence = {
            "computer_id": str(computer_id), "machine_outcome": plan["machine_outcome"],
            "machine_reason": plan["machine_reason"], "selection_digest": digest,
            "previous_subject_id": older["subject_id"], "selected_subject_id": selected["subject_id"],
            "estimated_id": plan["estimated_id"],
        }
        cur.execute(
            "SELECT operations.begin_change('computer.ninja_record.supersede', %s, %s::jsonb,"
            " 'process', NULL, %s, '', %s, true)",
            ("One Ninja record has current agent contact; its predecessor is offline.",
             json.dumps(evidence), _PROCESS, tenant_id),
        )
        action_id = cur.fetchone()[0]
        arguments = (
            tenant_id, computer_id, older["subject_id"], selected["subject_id"], action_id,
            older["input_version"], selected["input_version"],
            older["association_version"], selected["association_version"],
        )
        if plan["estimated_id"]:
            cur.execute(
                "SELECT operations.supersede_ninja_computer_record(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (*arguments, plan["estimated_id"]),
            )
        else:
            cur.execute(
                "SELECT operations.supersede_ninja_computer_record(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                arguments,
            )
    if selected["device_id"] is None:
        cur.execute(
            "SELECT operations.set_source_association(%s, d.entity_id, 'device', 'ninja_successor',"
            " 1, %s, %s, 'system', NULL, %s, %s::jsonb)"
            " FROM operations.devices d WHERE d.tenant_id = %s AND d.id = %s AND d.deleted_at IS NULL",
            (selected["subject_id"], "Selected current Ninja record", selected["association_version"],
             _PROCESS, json.dumps({"selection_digest": digest}), tenant_id, computer_id),
        )
        row = cur.fetchone()
        if not row or row[0] != selected["association_version"] + 1:
            raise ValueError("The selected Ninja record was not attached. No change was saved.")
    return {"computer_id": str(computer_id), "selected_subject_id": selected["subject_id"],
            "superseded_count": len(plan["records"]) - 1}


def run(tenant_id: int, computer_id: UUID, candidate_id: UUID | None, reviewed_digest: str | None) -> dict:
    with db.transaction() as cur:
        if reviewed_digest is None:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT set_config('operations.tenant_id', %s, true)", (str(tenant_id),))
        else:
            guard_findings_writes(cur, tenant_id)
        plan = _plan(cur, tenant_id, computer_id, candidate_id)
        digest = _digest(plan)
        if reviewed_digest is None:
            return plan | {"digest": digest}
        if digest != reviewed_digest:
            raise ValueError("Reviewed Ninja successor evidence changed. Preview the Computer again.")
        return _apply(cur, tenant_id, computer_id, plan, digest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--computer-id", type=UUID, required=True)
    parser.add_argument("--candidate-id", type=UUID)
    parser.add_argument("--apply-reviewed-digest", help="Apply the reviewed preview to this Computer")
    args = parser.parse_args()
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=2)
    print(json.dumps(run(args.tenant_id, args.computer_id, args.candidate_id, args.apply_reviewed_digest),
                     sort_keys=True, default=str))


if __name__ == "__main__":
    main()
