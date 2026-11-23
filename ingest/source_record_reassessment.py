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
  are still those of the preview. It reruns the match and locks the selected
  Computer's effective owner before attaching. A changed row returns to review. ``same`` needs
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
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ingest import db, preview_identity_reconciliation
from ingest.identity.matching import (
    OwnershipMatchDeferred,
    MATCHER_RULE_REVISION,
    _identity_exclusions,
    _resolve_match,
    load_identity_match_policies,
    preview_match,
    record_name_short,
)
from shared.findings_contract import guard_findings_writes
from shared.identity_evidence import CONFLICT_RULE_REVISION

_ATTACHED_OUTCOMES = {
    "unchanged": "same",
    "retained_evidence": "same",
    "proposed_reattachment": "changed",
    "review_required": "ambiguous",
    "no_independent_match": "unmatched",
}


def _policy_fingerprint(cur: Any, tenant_id: int) -> str:
    """Pin policy data and the declared matching revisions used for a preview."""
    cur.execute(
        """
        SELECT jsonb_build_object(
          'policies', COALESCE((
              SELECT jsonb_agg(to_jsonb(p) ORDER BY p.matcher)
                FROM operations.identity_match_policies p WHERE p.tenant_id = %s
          ), '[]'::jsonb),
          'identity_types', COALESCE((
              SELECT jsonb_agg(t.name ORDER BY t.name)
                FROM operations.entity_types t WHERE t.is_identity_signal
          ), '[]'::jsonb),
          'source_name_kinds', COALESCE((
              SELECT jsonb_agg(to_jsonb(k) ORDER BY k.platform, k.record_type)
                FROM operations.source_name_kinds k
          ), '[]'::jsonb),
          'serial_rejections', COALESCE((
              SELECT jsonb_agg(r.normalized_value ORDER BY r.normalized_value)
                FROM operations.identity_value_rejections r
               WHERE r.value_kind = 'serial' AND r.enabled
          ), '[]'::jsonb)
        )
        """,
        (tenant_id,),
    )
    payload = json.dumps(
        {"reference_data": cur.fetchone()[0], "matcher_revision": MATCHER_RULE_REVISION,
         "conflict_revision": CONFLICT_RULE_REVISION},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unattached(
    cur: Any, tenant_id: int, identity_types: list[str], rejected_serials: frozenset[str],
    subject_ids: list[uuid.UUID] | None = None,
    *, universal: bool = False,
) -> list[dict[str, Any]]:
    policies = load_identity_match_policies(cur, tenant_id)
    cur.execute(
        """
        SELECT o.observation_id, o.source_instance_id, o.entity_type, o.platform,
               o.entity_key, operations.computer_client_independent_evidence(o.tenant_id, o.observation_id),
               o.canonical_data, s.id, s.input_version,
               s.association_version, s.external_namespace, s.parent_external_namespace,
               s.parent_external_id, s.external_id
          FROM operations.entity_observation_current o
          JOIN operations.source_record_subjects s
            ON s.tenant_id = o.tenant_id AND s.observation_id = o.observation_id
         WHERE o.tenant_id = %s AND o.device_id IS NULL AND o.active
           AND o.entity_type = ANY(%s::text[])
           AND o.external_namespace <> 'device-health'
           AND (%s::uuid[] IS NULL OR s.id = ANY(%s::uuid[]))
         ORDER BY o.observation_id
        """,
        (tenant_id, identity_types, subject_ids, subject_ids),
    )
    rows = cur.fetchall()
    exclusions = _identity_exclusions(
        cur, tenant_id,
        [{"id": row[7], "observation_id": row[0]} for row in rows],
    )
    entries = []
    for (
        observation_id,
        source_instance_id,
        entity_type,
        platform,
        entity_key,
        client_id,
        data,
        subject_id,
        input_version,
        association_version,
        external_namespace,
        parent_external_namespace,
        parent_external_id,
        external_id,
    ) in rows:
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
            source_instance_id=source_instance_id,
            identity_types=identity_types,
            excluded_observation_ids=exclusions[subject_id],
            source_identity_key=(external_namespace, parent_external_namespace,
                                 parent_external_id, external_id),
            rejected_serials=rejected_serials,
            universal=universal,
            assess_globally=not universal,
        )
        result = preview.result
        if result is None:
            has_blocker = preview.ownership_deferred or any(
                attempt.blockers or attempt.missing or len(attempt.usable) > 1 for attempt in preview.attempts
            )
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
                "source_instance_id": str(source_instance_id) if source_instance_id else None,
                "field_origin": "unknown",
                "previous_device_id": None,
                "outcome": outcome,
                "proposed_device_id": str(proposed) if proposed else None,
                "matcher": result.matcher if result else None,
                "compared": result.compared if result else {},
                "candidates": (
                    [str(c) for c in result.candidates] if result else
                    sorted({str(c) for attempt in preview.attempts for c in attempt.candidates})
                ),
                "attempts": list(preview_identity_reconciliation._attempts(preview)),
                "ownership_deferred": preview.ownership_deferred,
                "missing": sorted({item for attempt in preview.attempts for item in attempt.missing}),
                "input_version": input_version,
                "association_version": association_version,
            }
        )
    return entries


def preview(
    tenant_id: int = 1, *, subject_ids: list[uuid.UUID] | None = None,
    universal: bool = False,
) -> dict[str, Any]:
    if tenant_id < 1:
        raise ValueError("tenant_id must be positive")
    if subject_ids is not None and (not subject_ids or len(set(subject_ids)) != len(subject_ids)):
        raise ValueError("scope must contain distinct source record IDs")
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute(
            "SELECT set_config('operations.tenant_id', %s, TRUE)", (str(tenant_id),)
        )
        policy_fingerprint = _policy_fingerprint(cur, tenant_id)
        cur.execute(
            "SELECT input_generation FROM operations.source_record_tenant_state WHERE tenant_id = %s",
            (tenant_id,),
        )
        generation_row = cur.fetchone()
        if generation_row is None:
            raise RuntimeError("source record generation is unavailable")
        input_generation = generation_row[0]
        attached = preview_identity_reconciliation._run_in_snapshot(
            cur, tenant_id, subject_ids=subject_ids, universal=universal,
            assess_globally=not universal,
        )
        identity_types = preview_identity_reconciliation._snapshot_identity_types(cur)
        cur.execute(
            """
            SELECT observation_id::text, id::text, input_version, association_version
              FROM operations.source_record_subjects WHERE tenant_id = %s
               AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[]))
            """,
            (tenant_id, subject_ids, subject_ids),
        )
        subjects = {row[0]: row[1:] for row in cur.fetchall()}
        rejected_serials = preview_identity_reconciliation._load_rejections(cur)
        unattached = _unattached(
            cur, tenant_id, identity_types, rejected_serials, subject_ids, universal=universal,
        )
    entries = []
    for entry in attached["entries"]:
        subject = subjects.get(entry["observation_id"])
        entries.append(
            {
                "subject_id": subject[0] if subject else None,
                "observation_id": entry["observation_id"],
                "entity_type": entry["entity_type"],
                "platform": entry["platform"],
                "source_instance_id": entry["source_instance_id"],
                "field_origin": "unknown",
                "previous_device_id": entry["previous_device_id"],
                "outcome": _ATTACHED_OUTCOMES[entry["outcome"]],
                "proposed_device_id": entry["proposed_device_id"],
                "matcher": entry["matcher"],
                "compared": entry["compared"],
                "candidates": list(entry["candidates"]),
                "attempts": list(entry["attempts"]),
                "ownership_deferred": entry["ownership_deferred"],
                "missing": sorted({item for attempt in entry["attempts"]
                                   for item in attempt.get("missing", [])}),
                "input_version": subject[1] if subject else None,
                "association_version": subject[2] if subject else None,
            }
        )
    entries.extend(unattached)
    if subject_ids is not None and {entry["subject_id"] for entry in entries} != {
        str(subject_id) for subject_id in subject_ids
    }:
        raise ValueError("scope includes unavailable or unsupported source records")
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["outcome"]] = summary.get(entry["outcome"], 0) + 1
    return {"tenant_id": tenant_id, "scope": sorted(map(str, subject_ids)) if subject_ids else None,
            "policy_fingerprint": policy_fingerprint,
            "input_generation": input_generation,
            "summary": summary, "entries": entries}


def _report_digest(report: dict[str, Any]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recover(saved: dict[str, Any]) -> dict[str, Any]:
    """Inspect committed history for an interrupted run without changing data."""
    report = saved["preview"]
    run_id = uuid.UUID(saved["run_id"])
    digest = _report_digest(report)
    if saved.get("preview_digest") != digest:
        raise ValueError("saved preview digest does not match")
    scope = report.get("scope") or []
    if (not scope or len(scope) != len(set(scope)) or len(scope) != len(report["entries"])
            or set(scope) != {entry["subject_id"] for entry in report["entries"]}):
        raise ValueError("recovery requires the original scoped preview")
    with db.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SELECT set_config('operations.tenant_id', %s, true)", (str(report["tenant_id"]),))
        cur.execute(
            """
            SELECT s.id::text, d.id::text, h.id::text,
                   h.evidence ->> 'association_version',
                   h.evidence ->> 'preview_digest',
                   (h.effective_to IS NULL AND l.entity_id = h.entity_id
                    AND s.association_version::text = h.evidence ->> 'association_version')
              FROM operations.entity_source_link_history h
              LEFT JOIN operations.source_record_subjects s
                ON s.tenant_id = h.tenant_id AND s.source_instance_id = h.source_instance_id
               AND s.external_namespace = h.external_namespace
               AND s.parent_external_namespace = h.parent_external_namespace
               AND s.parent_external_id = h.parent_external_id AND s.external_id = h.external_id
              LEFT JOIN operations.devices d ON d.tenant_id = h.tenant_id AND d.entity_id = h.entity_id
              LEFT JOIN operations.entity_source_links l
                ON l.tenant_id = s.tenant_id AND l.source_subject_id = s.id
             WHERE h.tenant_id = %s AND h.actor_process = 'ingest.source_record_reassessment'
               AND h.evidence ->> 'run_id' = %s
             ORDER BY s.id, h.effective_from, h.id
            """,
            (report["tenant_id"], str(run_id)),
        )
        history = cur.fetchall()
    by_subject = {}
    for subject_id, device_id, history_id, association_version, saved_digest, current in history:
        if saved_digest != digest or subject_id not in scope or subject_id in by_subject:
            raise ValueError("run history does not match the saved scope")
        by_subject[subject_id] = {
            "device_id": device_id, "history_id": history_id,
            "association_version": association_version, "current": bool(current),
        }
    entries = []
    for entry in report["entries"]:
        recorded = by_subject.get(entry["subject_id"])
        if recorded and recorded["device_id"] != entry["proposed_device_id"]:
            raise ValueError("run history target does not match the saved preview")
        eligible = entry["outcome"] == "newly_matched" and len(entry["candidates"]) == 1
        if recorded and not eligible:
            raise ValueError("run history contains an action outside the saved preview")
        status = ("applied_current" if recorded and recorded["current"] else
                  "applied_changed" if recorded else "not_recorded" if eligible else "not_applicable")
        entries.append({"subject_id": entry["subject_id"], "status": status, "history": recorded})
    return {"tenant_id": report["tenant_id"], "run_id": str(run_id),
            "preview_digest": digest, "entries": entries}


def apply(report: dict[str, Any], *, expected_digest: str, run_id: uuid.UUID) -> dict[str, Any]:
    """Apply the policy-covered rows that are still current; nothing else."""
    if not expected_digest or _report_digest(report) != expected_digest:
        raise ValueError("reviewed preview digest does not match")
    scope = report.get("scope") or []
    if (not scope or len(scope) != len(set(scope)) or len(scope) != len(report["entries"])
            or set(scope) != {entry["subject_id"] for entry in report["entries"]}):
        raise ValueError("apply requires a complete, explicit source record scope")
    tenant_id = report["tenant_id"]
    expected_generation = report.get("input_generation")
    applied, returned = [], []
    for entry in report["entries"]:
        if entry["outcome"] != "newly_matched" or len(entry["candidates"]) != 1:
            continue
        with db.transaction() as cur:
            # Fence candidate evidence before taking subject or owner locks.
            # Input transactions advance this generation at commit; holding
            # its row prevents a changed comparison universe from committing
            # while this action rechecks and associates the record.
            guard_findings_writes(cur, tenant_id)
            cur.execute("SELECT operations.lock_identity_reference_data(%s)", (tenant_id,))
            reference_lock = cur.fetchone()
            if not reference_lock or not reference_lock[0]:
                returned.append({**entry, "returned_reason": "identity policy is being changed"})
                continue
            if (not report.get("policy_fingerprint") or
                    _policy_fingerprint(cur, tenant_id) != report["policy_fingerprint"]):
                returned.append({**entry, "returned_reason": "identity policy changed since preview"})
                continue
            rejected_serials = preview_identity_reconciliation._load_rejections(cur)
            cur.execute(
                "SELECT operations.lock_source_record_generation(%s)",
                (tenant_id,),
            )
            generation = cur.fetchone()
            if generation is None or generation[0] is None:
                returned.append({**entry, "returned_reason": "input generation unavailable"})
                continue
            if expected_generation is None or generation[0] != expected_generation:
                returned.append({**entry, "returned_reason": "source evidence changed since preview"})
                continue
            cur.execute("SELECT operations.lock_source_record_subject(%s, %s)",
                        (tenant_id, entry["subject_id"]))
            subject = cur.fetchone()
            if not subject or not subject[0]:
                returned.append({**entry, "returned_reason": "source record unavailable"})
                continue
            cur.execute(
                """
                SELECT s.input_version, s.association_version, s.source_instance_id,
                       s.external_namespace, s.parent_external_namespace,
                       s.parent_external_id, s.external_id,
                       o.observation_id, o.entity_type, o.platform, o.entity_key,
                       o.canonical_data,
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
                returned.append(
                    {**entry, "returned_reason": "inputs changed since preview"}
                )
                continue
            if not row[13] or row[14] is not None:
                returned.append({**entry, "returned_reason": "record is no longer active and unattached"})
                continue
            cur.execute(
                "SELECT entity_class_id FROM operations.entity_source_links "
                "WHERE tenant_id = %s AND source_subject_id = %s",
                (tenant_id, entry["subject_id"]),
            )
            existing_link = cur.fetchone()
            if existing_link and existing_link[0] == "device":
                returned.append({**entry, "returned_reason": "already associated"})
                continue
            observation_id, entity_type, platform, entity_key, data, client_id = row[7:13]
            data = data or {}
            hostname = record_name_short(
                cur, platform, entity_type, data.get("hostname") or data.get("guest_name"), data.get("domain")
            )
            subject_id = uuid.UUID(str(entry["subject_id"]))
            exclusions = _identity_exclusions(
                cur, tenant_id,
                [{"id": subject_id, "observation_id": observation_id}],
            )
            try:
                current = _resolve_match(
                    cur, tenant_id=tenant_id, source_name=platform, external_id=entity_key,
                    entity_type=entity_type, serial=data.get("serial_number"), vm_uuid=data.get("vm_uuid"),
                    hostname=hostname or None, macs=data.get("macs") or [], client_id=client_id,
                    policies=load_identity_match_policies(cur, tenant_id), is_online=data.get("is_online"),
                    source_instance_id=row[2], skip_source_identity=True,
                    identity_types=preview_identity_reconciliation._snapshot_identity_types(cur),
                    excluded_observation_ids=exclusions[subject_id], trace=False,
                    source_identity_key=tuple(row[3:7]),
                    rejected_serials=rejected_serials,
                ).result
            except OwnershipMatchDeferred:
                current = None
            if (current is None or len(current.candidates) != 1
                    or str(current.device_id) != entry["proposed_device_id"]
                    or current.matcher != entry["matcher"]):
                returned.append({**entry, "returned_reason": "match changed since preview"})
                continue
            cur.execute(
                "SELECT entity_id, operations.lock_computer_client_scope(%s, id, client_id) "
                "FROM operations.devices WHERE tenant_id = %s AND id = %s AND deleted_at IS NULL",
                (tenant_id, tenant_id, entry["proposed_device_id"]),
            )
            owner = cur.fetchone()
            if not owner or owner[0] is None or not owner[1]:
                returned.append({**entry, "returned_reason": "candidate ownership changed"})
                continue
            cur.execute(
                "SELECT operations.set_source_association(%s, %s, 'device', 'reassessment', 1,"
                " 'reviewed reassessment', %s, 'system', NULL,"
                " 'ingest.source_record_reassessment', %s::jsonb)",
                (entry["subject_id"], owner[0], row[1], json.dumps({
                    "run_id": str(run_id), "preview_digest": expected_digest,
                    "matcher": current.matcher, "preview_generation": report["input_generation"],
                    "compared": current.compared,
                })),
            )
            association_version = cur.fetchone()[0]
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
                    "association_version": association_version,
                    "rollback": "clear this association with set_source_association(p_entity => NULL)",
                }
            )
        # The deferred source-record trigger increments once per tenant and
        # transaction after this association commits.
        expected_generation += 1
    review = [
        e
        for e in report["entries"]
        if e["outcome"] in ("changed", "ambiguous", "unmatched")
    ]
    return {
        "tenant_id": tenant_id,
        "run_id": str(run_id),
        "preview_digest": expected_digest,
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


def _replace_report(path: Path, payload: dict[str, Any]) -> None:
    """Keep the saved preview intact if writing the completed report fails."""
    target = path.resolve()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time association reassessment")
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--subject-id", type=uuid.UUID, action="append", dest="subject_ids",
                        help="source record ID to include; repeat for each record")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--recover-from", type=Path, help="saved interrupted run report")
    parser.add_argument("--expected-digest", help="digest of the reviewed preview required for apply")
    args = parser.parse_args()
    if args.apply and not args.expected_digest:
        parser.error("--apply requires --expected-digest")
    if args.apply and not args.subject_ids:
        parser.error("--apply requires at least one --subject-id")
    if args.expected_digest and not args.apply:
        parser.error("--expected-digest requires --apply")
    if args.recover_from and args.subject_ids:
        parser.error("--recover-from uses the scope in the saved report")
    from ingest.config import settings

    db.init(settings.postgres_dsn, min_size=1, max_size=2)
    if args.recover_from:
        with args.recover_from.open(encoding="utf-8") as handle:
            saved = json.load(handle)
        result = recover(saved)
        _write(args.output, result)
        print(json.dumps({"run_id": result["run_id"], "entries": len(result["entries"])}))
        return
    report = preview(args.tenant_id, subject_ids=args.subject_ids)
    _write(args.output, report)
    result = report
    run_id = uuid.uuid4()
    if args.apply:
        if _report_digest(report) != args.expected_digest:
            raise ValueError("reviewed preview digest does not match")
        _replace_report(args.output, {
            "run_id": str(run_id), "status": "applying", "preview": report,
            "preview_digest": args.expected_digest,
        })
        result = {**apply(report, expected_digest=args.expected_digest, run_id=run_id), "preview": report}
        _replace_report(args.output, result)
    counts = {
        "preview": report["summary"],
        "preview_digest": _report_digest(report),
        "applied": len(result.get("applied", [])),
        "returned_to_review": len(result.get("returned_to_review", [])),
        "review_required": len(result.get("review_required", [])),
        "run_id": str(run_id),
    }
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
