"""Client resolver (Track C batch C2).

Runs before the device resolver drains observations. Scans `org`
observations with client_id NULL and walks the strictly-exclusive ladder
from BLUEPRINT Track C.3:

    Rung 1 — id-link.  If operations.client_links has a row for
             (source, external_id) the observation already carries the
             client_id from source_observations._load_client_links. A
             name change on a mapped group DOES NOT re-match — it emits
             a `client_name_conflict` finding for operator apply.

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
            FROM operations.entity_observations
            WHERE tenant_id = %s
              AND entity_type = 'org'
              AND client_id IS NULL
            ORDER BY source_binding_id, entity_key, observed_at DESC
            """,
            (_TENANT_ID,),
        )
        rows = cur.fetchall()
        log.info("client_resolver: %d unattached org groups", len(rows))

        source_by_binding = _load_source_by_binding(cur)
        source_ids_by_name = _load_source_ids_by_name(cur)
        for obs_id, binding_id, entity_key, platform, canonical_data, observed_at in rows:
            cd = canonical_data or {}
            group_name = (cd.get("name") or "").strip()
            normalized = cd.get("normalized_name") or _norm(group_name)
            source_id = source_by_binding.get(binding_id)

            if not group_name or not normalized:
                # e.g. LMI "-1" placeholder with empty name.
                continue

            if normalized in placeholders or cd.get("is_placeholder"):
                continue

            if normalized in excludes:
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

        # Rung 1 drift check — any mapped link whose latest observed name
        # no longer matches emits client_name_conflict.
        _check_name_drift(cur, source_ids_by_name)

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


def _load_source_ids_by_name(cur) -> dict[str, int]:
    cur.execute("SELECT name, id FROM operations.sources")
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
        UPDATE operations.entity_observations
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
        UPDATE operations.entity_observations
        SET client_id = %s
        WHERE tenant_id = %s
          AND source_binding_id = %s
          AND entity_type <> 'org'
          AND client_id IS NULL
          AND canonical_data ->> 'platform_group_id' = %s
        """,
        (client_id, _TENANT_ID, binding_id, entity_key),
    )
    if source_id is not None:
        cur.execute(
            """
            INSERT INTO operations.client_links
                (id, version, tenant_id, client_id, source_id, external_id,
                 external_name, created_at, created_reason)
            VALUES (gen_random_uuid(), 0, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (tenant_id, source_id, external_id)
            DO UPDATE SET external_name = EXCLUDED.external_name
            """,
            (
                _TENANT_ID, client_id, source_id, entity_key,
                group_name, reason,
            ),
        )
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
                 first_seen_at, last_seen_at)
            VALUES (gen_random_uuid(), 1, %s, %s, %s, 'open', 1, %s::jsonb,
                    NOW(), NOW())
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


def _finding_type_id(cur, name: str) -> int | None:
    cur.execute(
        "SELECT id FROM operations.finding_types WHERE name = %s LIMIT 1",
        (name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


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
                WHERE status IN ('open', 'acknowledged')
            DO UPDATE SET
                last_detected_at = EXCLUDED.last_detected_at,
                details          = EXCLUDED.details
            """,
            (
                _TENANT_ID, ft_id, condition_key, severity,
                json.dumps(subject_ref), json.dumps(details), now, now,
            ),
        )
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
                WHERE condition_key > '' AND status IN ('open', 'acknowledged')
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
        """
        UPDATE operations.admin_findings
        SET status = 'resolved', resolved_at = NOW()
        WHERE tenant_id = %s AND finding_type_id = %s
          AND condition_key = %s
          AND status IN ('open', 'acknowledged')
        """,
        (_TENANT_ID, ft_id, condition_key),
    )


def _check_name_drift(cur, source_ids_by_name: dict[str, int]) -> None:
    """A mapped link seeing a different display name = one-click apply finding."""
    cur.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (source_binding_id, entity_key)
                   source_binding_id, entity_key,
                   canonical_data ->> 'name' AS observed_name,
                   canonical_data ->> 'normalized_name' AS observed_norm
            FROM operations.entity_observations
            WHERE tenant_id = %s AND entity_type = 'org'
              AND client_id IS NOT NULL
            ORDER BY source_binding_id, entity_key, observed_at DESC
        )
        SELECT cl.id, cl.client_id, cl.source_id, cl.external_id,
               cl.external_name, l.observed_name, l.observed_norm,
               c.display_name
        FROM operations.client_links cl
        JOIN operations.source_bindings sb
             ON sb.enabled
        JOIN operations.source_instances si
             ON si.id = sb.source_instance_id AND si.source_id = cl.source_id
        JOIN latest l
             ON l.source_binding_id = sb.id AND l.entity_key = cl.external_id
        JOIN operations.clients c ON c.id = cl.client_id
        WHERE cl.tenant_id = %s
        """,
        (_TENANT_ID, _TENANT_ID),
    )
    drift_rows = cur.fetchall()
    for link_id, client_id, source_id, external_id, external_name, \
            observed_name, observed_norm, client_display in drift_rows:
        if not observed_name:
            continue
        client_norm = _norm(client_display)
        obs_norm = observed_norm or _norm(observed_name)
        if obs_norm == client_norm or obs_norm == _norm(external_name):
            _resolve_finding(cur, "client_name_conflict", _cond_link(link_id))
            continue
        _emit_finding(
            cur, "client_name_conflict",
            condition_key=_cond_link(link_id),
            subject_ref={
                "client_link_id": str(link_id),
                "client_id": str(client_id),
                "source_id": source_id,
                "external_id": external_id,
                "client_display_name": client_display,
                "external_name_stored": external_name,
                "observed_name": observed_name,
            },
            details={
                "observed_normalized": obs_norm,
                "client_normalized": client_norm,
            },
            severity="medium",
            admin=True,
        )
