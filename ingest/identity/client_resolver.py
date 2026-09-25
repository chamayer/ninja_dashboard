"""Client resolver (Track C batch C2).

Runs before the device resolver drains observations. Scans `org`
observations with client_id NULL and walks the strictly-exclusive ladder
from BLUEPRINT Track C.3:

    Rung 1 — id-link.  If operations.v_client_source_link has a row for
             (source, external_id) the observation already carries the
             client_id from source_observations._load_client_links. The
             source-reported group name remains visible as mapping evidence;
             it does not re-match or rename the canonical client.

    Rung 2 — exact normalized-name match against Client.display_name
             or an enabled ClientNameAlias row. On a single match the
             org observation gets client_id, and a client_link is minted
             (created_reason='resolver.name_match') so future runs
             short-circuit at rung 1. On multiple matches, emit
             `client_link_collision` and DO NOT attach.

    Rung 3 — suggestion only. Fuzzy / prefix / device-overlap does not
             attach; it appears in the candidate's evidence panel (C3).

    Rung 4 — no match. Upsert a client_candidate for operator review;
             emit `client_unattached_group`.

Placeholders (name in placeholder_org_names) and org_excludes rows are
skipped from candidacy, and empty-name groups (e.g. LMI "-1") never
become candidates. Both still appear as observations.

Attachment propagates: once the org gets a client_id, all
(source_binding, entity_key=<group_id>) org observations plus every
device observation whose canonical_data reports that platform_group_id
get client_id backfilled in place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ingest.conditions import record_assessment
from shared.conditions.contracts import Condition, EvaluationCoverage, Participant, Signal, Readiness

log = logging.getLogger(__name__)

_TENANT_ID = 1
_ORG_STRIP_RE = re.compile(r"[\s\-_.]")


def _norm(name: str | None) -> str:
    return _ORG_STRIP_RE.sub("", (name or "")).lower().strip()


def drain_client_resolution() -> int:
    """Resolve unattached org observations. Returns count attached."""
    from ingest import db

    attached = 0
    with db.transaction() as cur:
        cur.execute(f"SET LOCAL operations.tenant_id = {_TENANT_ID}")
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext('operations.client_resolver'))"
        )
        placeholders = _load_set(
            cur,
            "SELECT normalized_name FROM operations.placeholder_org_names"
            " WHERE tenant_id = %s",
            (_TENANT_ID,),
        )
        excludes = _load_set(
            cur,
            "SELECT normalized_name FROM operations.client_org_excludes"
            " WHERE tenant_id = %s AND enabled",
            (_TENANT_ID,),
        )
        name_index = _load_name_index(cur)

        cur.execute(
            """
            SELECT DISTINCT ON (source_binding_id, entity_key)
                   observation_id, source_binding_id, entity_key,
                   platform, canonical_data, observed_at
            FROM operations.entity_observation_current
            WHERE tenant_id = %s
              AND entity_type = 'org'
              AND active = TRUE
              AND client_id IS NULL
            ORDER BY source_binding_id, entity_key, observed_at DESC
            """,
            (_TENANT_ID,),
        )
        rows = cur.fetchall()
        log.info("client_resolver: %d unattached org groups", len(rows))

        source_by_binding = _load_source_by_binding(cur)
        for obs_id, binding_id, entity_key, platform, canonical_data, observed_at in rows:
            cd = canonical_data or {}
            group_name = (cd.get("name") or "").strip()
            normalized = cd.get("normalized_name") or _norm(group_name)
            source_id = source_by_binding.get(binding_id)

            if not group_name or not normalized:
                # e.g. LMI "-1" placeholder with empty name.
                # Surface as a standard Finding (nothing hidden rule)
                # so operators can decide whether to fix at source,
                # add to placeholder_org_names, or ignore. dedup keyed
                # on (source_binding, entity_key).
                _emit_unnamed_source_group_finding(
                    cur, binding_id, entity_key, source_id, platform,
                )
                continue

            if normalized in placeholders or cd.get("is_placeholder"):
                _resolve_finding(cur, "client_unattached_group", _cond_group(binding_id, entity_key))
                _resolve_finding(cur, "client_link_collision", _cond_group(binding_id, entity_key))
                continue

            if normalized in excludes:
                _resolve_finding(cur, "client_unattached_group", _cond_group(binding_id, entity_key))
                _resolve_finding(cur, "client_link_collision", _cond_group(binding_id, entity_key))
                continue

            matches = name_index.get(normalized) or []
            if len(matches) == 1:
                client_id = matches[0]
                _attach_group(
                    cur, source_id, binding_id, entity_key,
                    group_name, client_id, reason="resolver.name_match",
                )
                _clear_candidate(cur, normalized, client_id)
                _resolve_finding(cur, "client_unattached_group",
                                 _cond_group(binding_id, entity_key))
                attached += 1
                continue

            if len(matches) >= 2:
                _emit_finding(
                    cur, "client_link_collision",
                    condition_key=_cond_group(binding_id, entity_key),
                    subject_ref={
                        "platform": platform,
                        "source_binding_id": str(binding_id),
                        "external_id": entity_key,
                        "external_name": group_name,
                    },
                    details={
                        "normalized_name": normalized,
                        "candidate_client_ids": [str(cid) for cid in matches],
                    },
                    severity="high",
                    admin=True,
                )
                _upsert_candidate(
                    cur, normalized, group_name, source_id, entity_key, observed_at,
                )
                continue

            # Rung 4 — candidate + admin finding.
            _upsert_candidate(
                cur, normalized, group_name, source_id, entity_key, observed_at,
            )
            _emit_finding(
                cur, "client_unattached_group",
                condition_key=_cond_group(binding_id, entity_key),
                subject_ref={
                    "platform": platform,
                    "source_binding_id": str(binding_id),
                    "external_id": entity_key,
                    "external_name": group_name,
                },
                details={"normalized_name": normalized},
                severity="medium",
                admin=True,
            )

        # A mapped name difference is a client-level finding. It is not a
        # rematch or forced rename: operators can suppress it when the source
        # label is intentionally different.
        _check_name_drift(cur)
        _check_mapping_topology(cur)
        _retire_client_name_conflicts(cur)

    log.info("client_resolver: attached %d groups", attached)
    return attached


def _load_set(cur, sql: str, params: tuple) -> set[str]:
    cur.execute(sql, params)
    return {row[0] for row in cur.fetchall()}


def _load_source_by_binding(cur) -> dict[uuid.UUID, int]:
    cur.execute(
        """
        SELECT sb.id, si.source_id
        FROM operations.source_bindings sb
        JOIN operations.source_instances si ON si.id = sb.source_instance_id
        WHERE si.tenant_id = %s
        """,
        (_TENANT_ID,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _load_name_index(cur) -> dict[str, list[uuid.UUID]]:
    """normalized_name → [client_id, ...] from clients + enabled aliases."""
    index: dict[str, list[uuid.UUID]] = {}
    cur.execute(
        "SELECT id, display_name FROM operations.clients"
        " WHERE tenant_id = %s AND deleted_at IS NULL",
        (_TENANT_ID,),
    )
    for cid, name in cur.fetchall():
        n = _norm(name)
        if n:
            index.setdefault(n, []).append(cid)
    cur.execute(
        "SELECT client_id, normalized_name FROM operations.client_name_aliases"
        " WHERE tenant_id = %s AND enabled",
        (_TENANT_ID,),
    )
    for cid, n in cur.fetchall():
        if not n:
            continue
        bucket = index.setdefault(n, [])
        if cid not in bucket:
            bucket.append(cid)
    return index


def _attach_group(
    cur,
    source_id: int | None,
    binding_id: uuid.UUID,
    entity_key: str,
    group_name: str,
    client_id: uuid.UUID,
    reason: str,
) -> None:
    """Attach every org + device observation for this group; mint the link."""
    cur.execute(
        """
        UPDATE operations.entity_observation_current
        SET client_id = %s
        WHERE tenant_id = %s
          AND source_binding_id = %s
          AND entity_type = 'org'
          AND entity_key = %s
          AND client_id IS NULL
        """,
        (client_id, _TENANT_ID, binding_id, entity_key),
    )
    # Backfill device observations whose canonical_data records this group.
    cur.execute(
        """
        UPDATE operations.entity_observation_current
        SET client_id = %s
        WHERE tenant_id = %s
          AND source_binding_id = %s
          AND entity_type <> 'org'
          AND client_id IS NULL
          AND canonical_data ->> 'platform_group_id' = %s
        """,
        (client_id, _TENANT_ID, binding_id, entity_key),
    )
    # The client_links INSERT that stood here is retired with migration 0123.
    # Setting client_id on the observations above is the attachment; the link
    # is derived from that evidence by
    # sync_entity_source_links_from_observations().
    # Clear the unmatched_source_groups review row.
    if source_id is not None:
        cur.execute(
            """
            DELETE FROM operations.unmatched_source_groups
            WHERE tenant_id = %s AND source_id = %s AND external_id = %s
            """,
            (_TENANT_ID, source_id, entity_key),
        )


def _upsert_candidate(
    cur,
    normalized: str,
    display_name: str,
    source_id: int | None,
    entity_key: str,
    observed_at: datetime,
) -> None:
    ref = {
        "source_id": source_id,
        "external_id": entity_key,
        "external_name": display_name,
        "observed_at": observed_at.isoformat() if observed_at else None,
    }
    cur.execute(
        "SELECT source_refs, status FROM operations.client_candidates"
        " WHERE tenant_id = %s AND normalized_name = %s",
        (_TENANT_ID, normalized),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """
            INSERT INTO operations.client_candidates
                (id, version, tenant_id, normalized_name, display_name,
                 status, seen_count, source_refs,
                 first_seen_at, last_seen_at,
                 resolved_by, resolved_reason)
            VALUES (gen_random_uuid(), 1, %s, %s, %s, 'open', 1, %s::jsonb,
                    NOW(), NOW(), '', '')
            ON CONFLICT (tenant_id, normalized_name) DO NOTHING
            """,
            (_TENANT_ID, normalized, display_name, json.dumps([ref])),
        )
        return
    refs, status = row
    refs = list(refs or [])
    key = (ref["source_id"], ref["external_id"])
    refs = [r for r in refs if (r.get("source_id"), r.get("external_id")) != key]
    refs.append(ref)
    cur.execute(
        """
        UPDATE operations.client_candidates
        SET display_name = CASE WHEN status = 'open' AND %s <> ''
                                THEN %s ELSE display_name END,
            seen_count   = seen_count + 1,
            last_seen_at = NOW(),
            source_refs  = %s::jsonb
        WHERE tenant_id = %s AND normalized_name = %s
        """,
        (display_name, display_name, json.dumps(refs), _TENANT_ID, normalized),
    )


def _clear_candidate(cur, normalized: str, client_id: uuid.UUID) -> None:
    cur.execute(
        """
        UPDATE operations.client_candidates
        SET status = 'mapped',
            resolved_client_id = %s,
            resolved_at = NOW(),
            resolved_by = 'resolver',
            resolved_reason = 'name_match'
        WHERE tenant_id = %s AND normalized_name = %s
          AND status = 'open'
        """,
        (client_id, _TENANT_ID, normalized),
    )


def _cond_group(binding_id: uuid.UUID, entity_key: str) -> str:
    raw = f"client_resolver:{binding_id}:{entity_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _cond_link(link_id: uuid.UUID) -> str:
    raw = f"client_name_drift:{link_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _cond_topology(kind: str, source_id: int, normalized_name: str, client_id: uuid.UUID | None = None) -> str:
    raw = f"client_mapping_topology:{kind}:{source_id}:{normalized_name}:{client_id or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _finding_type_id(cur, name: str) -> int | None:
    cur.execute(
        "SELECT id FROM operations.finding_types WHERE name = %s LIMIT 1",
        (name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _emit_unnamed_source_group_finding(
    cur, binding_id, entity_key: str, source_id: int | None, platform: str,
) -> None:
    """Emit an `unnamed_source_group` Finding at the empty-name skip
    site. Per the "nothing hidden" rule — these groups used to be
    silently dropped before reaching the unmatched_source_group path.
    Dedup keyed on (source_binding, entity_key). Writes directly to
    operations.findings (standard table) rather than admin_findings.
    """
    ft_id = _finding_type_id(cur, "unnamed_source_group")
    if ft_id is None:
        return
    now = datetime.now(timezone.utc)
    cond = _cond_group(binding_id, entity_key)
    cur.execute(
        """
        INSERT INTO operations.findings (
            id, version, tenant_id, finding_type_id, client_id,
            subject_type, subject_id, subject_layer,
            subject_layer_entity_id, finding_details, condition_key,
            severity, confidence, status,
            first_seen_at, last_seen_at, last_detected_at
        ) VALUES (
            gen_random_uuid(), 1, %s, %s, NULL,
            'source_binding', %s, '', NULL,
            %s::jsonb, %s,
            'low', 'confirmed', 'open',
            %s, %s, %s
        )
        ON CONFLICT (tenant_id, condition_key)
        WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        DO UPDATE SET
            last_seen_at = NOW(),
            last_detected_at = NOW(),
            finding_details = EXCLUDED.finding_details
        """,
        (
            _TENANT_ID, ft_id, binding_id,
            json.dumps({
                "source_binding_id": str(binding_id),
                "entity_key": entity_key,
                "platform": platform,
                "source_id": source_id,
            }),
            cond,
            now, now, now,
        ),
    )


def _emit_finding(
    cur,
    type_name: str,
    *,
    condition_key: str,
    subject_ref: dict[str, Any],
    details: dict[str, Any],
    severity: str,
    admin: bool,
    client_id: uuid.UUID | None = None,
) -> None:
    ft_id = _finding_type_id(cur, type_name)
    if ft_id is None:
        return
    now = datetime.now(timezone.utc)
    if admin:
        cur.execute(
            """
            INSERT INTO operations.admin_findings (
                id, version, tenant_id, finding_type_id, condition_key, severity,
                status, subject_ref, details, first_detected_at, last_detected_at
            ) VALUES (
                gen_random_uuid(), 1, %s, %s, %s, %s, 'open',
                %s::jsonb, %s::jsonb, %s, %s
            )
            ON CONFLICT (tenant_id, condition_key)
                WHERE status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                last_detected_at = EXCLUDED.last_detected_at,
                details          = EXCLUDED.details
            """,
            (
                _TENANT_ID, ft_id, condition_key, severity,
                json.dumps(subject_ref), json.dumps(details), now, now,
            ),
        )
        _record_resolver_assessment(cur, type_name, condition_key, subject_ref, now)
    else:
        # Entity finding — subject_type='client', subject_id=client_id.
        if client_id is None:
            return
        cur.execute(
            """
            INSERT INTO operations.findings (
                id, version, tenant_id, finding_type_id, client_id,
                subject_type, subject_id, finding_details,
                condition_key, severity, confidence, status,
                first_seen_at, last_seen_at, last_detected_at
            ) VALUES (
                gen_random_uuid(), 1, %s, %s, %s,
                'client', %s, %s::jsonb,
                %s, %s, 'confirmed', 'open',
                %s, %s, %s
            )
            ON CONFLICT (tenant_id, condition_key)
                WHERE condition_key > '' AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
            DO UPDATE SET
                last_seen_at     = EXCLUDED.last_seen_at,
                last_detected_at = EXCLUDED.last_detected_at,
                finding_details  = EXCLUDED.finding_details,
                status           = CASE
                    WHEN findings.status = 'resolved' THEN 'open'
                    ELSE findings.status
                END
            """,
            (
                _TENANT_ID, ft_id, client_id,
                client_id, json.dumps(details),
                condition_key, severity,
                now, now, now,
            ),
        )


def _resolve_finding(cur, type_name: str, condition_key: str) -> None:
    ft_id = _finding_type_id(cur, type_name)
    if ft_id is None:
        return
    cur.execute(
        """SELECT id, subject_ref FROM operations.admin_findings
           WHERE tenant_id = %s AND finding_type_id = %s AND condition_key = %s
           ORDER BY last_detected_at DESC LIMIT 1""",
        (_TENANT_ID, ft_id, condition_key),
    )
    row = cur.fetchone()
    assessment = None
    if row is not None:
        subject_ref = row[1] or {}
        assessment = _record_resolver_assessment(
            cur, type_name, condition_key, subject_ref, datetime.now(timezone.utc)
        )
    if not assessment or not assessment.get("may_clear"):
        return
    cur.execute(
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = NOW()
        WHERE tenant_id = %s AND finding_type_id = %s
          AND condition_key = %s
          AND status IN ('open', 'acknowledged')
        """,
        (_TENANT_ID, ft_id, condition_key),
    )


def _record_resolver_assessment(
    cur: Any,
    type_name: str,
    condition_key: str,
    subject_ref: dict[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    """Persist the resolver's complete current-observation evaluation."""
    binding_id = subject_ref.get("source_binding_id")
    participant = (
        Participant("source_binding", str(binding_id), "affected", _TENANT_ID)
        if binding_id
        else None
    )
    cur.execute(
        """SELECT id, status FROM operations.admin_findings
           WHERE tenant_id = %s AND condition_key = %s
           ORDER BY last_detected_at DESC LIMIT 1""",
        (_TENANT_ID, condition_key),
    )
    row = cur.fetchone()
    if row is None:
        return None
    finding_id, status = row
    participants = (participant,) if participant else ()
    condition = Condition(
        _TENANT_ID, "admin", str(finding_id), type_name, condition_key, status, participants
    )
    signals = (
        (Signal("identity", participant, Readiness.READY, "resolver:current_observation"),)
        if participant
        else ()
    )
    return record_assessment(
        cur,
        condition,
        signals,
        EvaluationCoverage(True, True, True, True),
        now=now,
        reevaluation_key=f"client-resolver:{condition_key}",
        participant=participant,
    )


def _retire_client_name_conflicts(cur) -> None:
    """Resolve legacy admin rows after client name differences moved to Findings.

    The entity-class ``client_name_conflict`` rows emitted below are the
    operator-facing findings. Earlier releases wrote the same condition into
    ``admin_findings`` and offered a forced client rename, which is retired.
    """
    ft_id = _finding_type_id(cur, "client_name_conflict")
    if ft_id is None:
        return
    cur.execute(
        """
        UPDATE operations.admin_findings
           SET status = 'resolved', resolved_at = NOW()
         WHERE tenant_id = %s
           AND finding_type_id = %s
           AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        """,
        (_TENANT_ID, ft_id),
    )


def _resolve_entity_finding(cur, type_name: str, condition_key: str) -> None:
    """Resolve an entity finding whose evidence no longer meets its condition."""
    ft_id = _finding_type_id(cur, type_name)
    if ft_id is None:
        return
    cur.execute(
        """
        UPDATE operations.findings
           SET status = 'resolved', resolved_at = NOW()
         WHERE tenant_id = %s
           AND finding_type_id = %s
           AND condition_key = %s
           AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
        """,
        (_TENANT_ID, ft_id, condition_key),
    )


def _check_name_drift(cur) -> None:
    """Emit a client finding when a mapped source group uses another name.

    Mapping and naming are distinct operator decisions. The source reference
    remains attached to the canonical client; the finding is reviewable and
    suppressible when the difference is intentional.
    """
    cur.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (source_binding_id, entity_key)
                   source_binding_id, entity_key,
                   canonical_data ->> 'name' AS observed_name,
                   canonical_data ->> 'normalized_name' AS observed_norm,
                   COALESCE((canonical_data ->> 'is_placeholder')::boolean, FALSE) AS is_placeholder
              FROM operations.entity_observation_current
             WHERE tenant_id = %s
               AND entity_type = 'org'
               AND client_id IS NOT NULL
               AND active = TRUE
             ORDER BY source_binding_id, entity_key, observed_at DESC
        ), observed AS (
            SELECT link.source_link_id, link.client_id, link.source_id, link.external_id,
                   binding.id AS source_binding_id, latest.observed_name, latest.observed_norm,
                   link.mapping_state
          FROM operations.v_client_source_mapping_effective link
          JOIN operations.source_bindings binding ON binding.enabled
          JOIN operations.source_instances instance
            ON instance.id = binding.source_instance_id
           AND instance.source_id = link.source_id
          JOIN latest
            ON latest.source_binding_id = binding.id
           AND latest.entity_key = link.external_id
         WHERE link.tenant_id = %s
           AND NOT latest.is_placeholder
        ), peers AS (
            SELECT client_id,
                   count(DISTINCT observed_name) AS distinct_name_count,
                   array_agg(DISTINCT observed_name ORDER BY observed_name) AS peer_names
              FROM observed
             WHERE observed_name <> ''
             GROUP BY client_id
        )
        SELECT observed.source_link_id, observed.client_id, observed.source_id, observed.external_id,
               observed.source_binding_id, observed.observed_name, observed.observed_norm,
               observed.mapping_state, peers.distinct_name_count, peers.peer_names
          FROM observed
          JOIN peers ON peers.client_id = observed.client_id
        """,
        (_TENANT_ID, _TENANT_ID),
    )
    active_conditions: set[str] = set()
    for (
        link_id,
        client_id,
        source_id,
        external_id,
        source_binding_id,
        observed_name,
        observed_norm,
        mapping_state,
        distinct_name_count,
        peer_names,
    ) in cur.fetchall():
        if not observed_name:
            continue
        condition_key = _cond_link(link_id)
        if mapping_state in {"explicit", "ignored"}:
            _resolve_entity_finding(cur, "client_name_conflict", condition_key)
            continue
        if distinct_name_count < 2:
            _resolve_entity_finding(cur, "client_name_conflict", condition_key)
            continue
        active_conditions.add(condition_key)
        _emit_finding(
            cur,
            "client_name_conflict",
            condition_key=condition_key,
            subject_ref={},
            details={
                "source_binding_id": str(source_binding_id),
                "source_link_id": str(link_id),
                "source_id": source_id,
                "external_id": external_id,
                "observed_name": observed_name,
                "peer_source_names": peer_names,
            },
            severity="low" if mapping_state == "automatic" else "medium",
            admin=False,
            client_id=client_id,
        )
    _resolve_unseen_client_name_conflicts(cur, active_conditions)


def _resolve_unseen_client_name_conflicts(cur, active_conditions: set[str]) -> None:
    """Withdraw drift findings whose active source evidence has disappeared."""
    ft_id = _finding_type_id(cur, "client_name_conflict")
    if ft_id is None:
        return
    params: list[Any] = [_TENANT_ID, ft_id]
    where = ""
    if active_conditions:
        where = " AND condition_key <> ALL(%s)"
        params.append(list(active_conditions))
    cur.execute(
        f"""
        UPDATE operations.findings
           SET status = 'resolved', resolved_at = NOW()
         WHERE tenant_id = %s
           AND finding_type_id = %s
           AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
           {where}
        """,
        params,
    )


def _check_mapping_topology(cur) -> None:
    """Surface duplicate source groups without altering source-link identity.

    A shared source-group name mapped to different clients is a split.  The
    same normalized source-group name appearing under multiple external IDs for
    one client is a possible duplicate/merge.  Explicit and ignored decisions
    are intentional operator outcomes, so they do not create review findings.
    """
    cur.execute(
        """
        WITH current_links AS (
            SELECT link.source_link_id, link.source_id, link.client_id,
                   link.external_id, link.observed_name,
                   regexp_replace(lower(link.observed_name), '[\\s\\-_.]', '', 'g') AS normalized_name
              FROM operations.v_client_source_mapping_effective link
             WHERE link.tenant_id = %s
               AND link.missing_since IS NULL
               AND link.observed_name IS NOT NULL
               AND link.observed_name <> ''
               AND link.mapping_state NOT IN ('explicit', 'ignored')
        ), splits AS (
            SELECT source_id, normalized_name,
                   array_agg(DISTINCT client_id::text ORDER BY client_id::text) AS client_ids,
                   array_agg(DISTINCT external_id ORDER BY external_id) AS external_ids,
                   array_agg(DISTINCT observed_name ORDER BY observed_name) AS source_group_names,
                   array_agg(DISTINCT source_link_id::text ORDER BY source_link_id::text) AS source_link_ids
              FROM current_links
             GROUP BY source_id, normalized_name
            HAVING count(DISTINCT client_id) > 1
        ), merges AS (
            SELECT source_id, client_id, normalized_name,
                   array_agg(DISTINCT external_id ORDER BY external_id) AS external_ids,
                   array_agg(DISTINCT observed_name ORDER BY observed_name) AS source_group_names,
                   array_agg(DISTINCT source_link_id::text ORDER BY source_link_id::text) AS source_link_ids
              FROM current_links
             GROUP BY source_id, client_id, normalized_name
            HAVING count(DISTINCT external_id) > 1
        )
        SELECT 'split', source_id, NULL::uuid, normalized_name,
               client_ids, external_ids, source_group_names, source_link_ids
          FROM splits
        UNION ALL
        SELECT 'merge', source_id, client_id, normalized_name,
               ARRAY[client_id::text], external_ids, source_group_names, source_link_ids
          FROM merges
        """,
        (_TENANT_ID,),
    )
    active: dict[str, set[str]] = {"split": set(), "merge": set()}
    for kind, source_id, client_id, normalized_name, client_ids, external_ids, source_group_names, source_link_ids in cur.fetchall():
        condition_key = _cond_topology(kind, source_id, normalized_name, client_id)
        active[kind].add(condition_key)
        _emit_finding(
            cur,
            "client_link_collision" if kind == "split" else "client_source_group_merge",
            condition_key=condition_key,
            subject_ref={"source_id": source_id, "external_id": external_ids[0]},
            details={
                "topology": kind,
                "source_id": source_id,
                "normalized_name": normalized_name,
                "candidate_client_ids": client_ids,
                "external_ids": external_ids,
                "source_group_names": source_group_names,
                "source_link_ids": source_link_ids,
            },
            severity="high" if kind == "split" else "medium",
            admin=True,
        )
    _resolve_unseen_topology_findings(cur, "client_link_collision", "split", active["split"])
    _resolve_unseen_topology_findings(cur, "client_source_group_merge", "merge", active["merge"])


def _resolve_unseen_topology_findings(
    cur, type_name: str, topology: str, active_conditions: set[str]
) -> None:
    ft_id = _finding_type_id(cur, type_name)
    if ft_id is None:
        return
    params: list[Any] = [_TENANT_ID, ft_id, topology]
    where = ""
    if active_conditions:
        where = " AND condition_key <> ALL(%s)"
        params.append(list(active_conditions))
    cur.execute(
        f"""
        UPDATE operations.admin_findings
           SET status = 'resolved', resolved_at = NOW()
         WHERE tenant_id = %s
           AND finding_type_id = %s
           AND details ->> 'topology' = %s
           AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
           {where}
        """,
        params,
    )
