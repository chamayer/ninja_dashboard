"""Classify current source-client evidence for a Computer.

This is the evidence portion of PLAN-045, not an ownership writer. The caller
must supply only current, applicable source records. Human decisions and the
atomic projection of dependent client scopes are handled separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID


@dataclass(frozen=True)
class SourceClientEvidence:
    status: str
    client_id: UUID | None
    known_client_count: int
    unknown_record_count: int


@dataclass(frozen=True)
class DecisionProtectedEvidence:
    """Current evidence compared with an explicitly selected client.

    This comparison does not determine whether a historical decision is still
    applicable. The caller must establish the decision's scope and provenance.
    """

    selected_client_id: UUID
    evidence: SourceClientEvidence
    contradicting_client_ids: frozenset[UUID]


def classify_source_clients(client_ids: Iterable[UUID | None]) -> SourceClientEvidence:
    """Resolve one known unanimous client; never infer a client from missing evidence."""
    clients: set[UUID] = set()
    records = unknown = 0
    for client_id in client_ids:
        records += 1
        if client_id is None:
            unknown += 1
        else:
            clients.add(client_id)
    if len(clients) > 1:
        return SourceClientEvidence("conflict", None, len(clients), unknown)
    if records == 0 or unknown:
        return SourceClientEvidence("unknown", None, len(clients), unknown)
    return SourceClientEvidence("resolved", next(iter(clients)), 1, 0)


def compare_explicit_client_decision(
    selected_client_id: UUID, client_ids: Iterable[UUID | None]
) -> DecisionProtectedEvidence:
    """Compare current records to a verified, applicable human client decision.

    Unknown evidence cannot itself contradict a selected client, but remains
    visible in the evidence classification. Legacy accepted evidence keys are
    not client decisions and must not be passed as one.
    """
    records = tuple(client_ids)
    return DecisionProtectedEvidence(
        selected_client_id=selected_client_id,
        evidence=classify_source_clients(records),
        contradicting_client_ids=frozenset(
            client_id
            for client_id in records
            if client_id is not None and client_id != selected_client_id
        ),
    )


def reconcile_cycle(tenant_id: int, *, batch_size: int = 100) -> dict[str, int]:
    """Project every live Computer, then drain inputs dirtied during the sweep.

    Candidate pages are bounded, and each Computer is projected atomically in
    its own transaction. Failures escape to the resolver job; the dirty state
    and a subsequent full sweep provide retry rather than silently certifying
    incomplete work. The findings guard is acquired before row locks because a
    resolved move can update device findings.
    """
    return _reconcile(tenant_id, batch_size=batch_size, full_sweep=True)


def reconcile_dirty(tenant_id: int, *, batch_size: int = 100) -> dict[str, int]:
    """Settle new invalidations without repeating the full fleet sweep."""
    return _reconcile(tenant_id, batch_size=batch_size, full_sweep=False)


def _reconcile(tenant_id: int, *, batch_size: int, full_sweep: bool) -> dict[str, int]:
    from ingest import db

    if batch_size < 1 or batch_size > 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    counts: dict[str, int] = {}
    last_id: UUID | None = None

    def project(cur, device_id) -> None:
        cur.execute(
            "SELECT operations.project_computer_client(%s::bigint, %s::uuid)",
            (tenant_id, device_id),
        )
        status = cur.fetchone()[0]
        counts[status] = counts.get(status, 0) + 1

    def select_device_ids(query: str, params: tuple) -> list[UUID]:
        # Candidate discovery must not hold the exclusive findings guard. Each
        # selected Computer is re-read and projected atomically under that guard.
        with db.transaction() as cur:
            cur.execute("SELECT set_config('operations.tenant_id', %s, true)", (str(tenant_id),))
            cur.execute(query, params)
            return [row[0] for row in cur.fetchall()]

    def project_each(device_ids: list[UUID]) -> None:
        for device_id in device_ids:
            with db.findings_transaction(tenant_id) as cur:
                project(cur, device_id)

    while full_sweep:
        device_ids = select_device_ids(
            """
            SELECT id FROM operations.devices
             WHERE tenant_id = %s AND deleted_at IS NULL
               AND (%s::uuid IS NULL OR id > %s::uuid)
             ORDER BY id LIMIT %s
            """,
            (tenant_id, last_id, last_id, batch_size),
        )
        if not device_ids:
            break
        project_each(device_ids)
        last_id = device_ids[-1]

    # A new Computer starts dirty even if it sorts before a full-sweep cursor.
    # Bound repeated selection pages so a constantly changing fleet reports a
    # retry instead of leaving a resolver job running forever.
    for _ in range(100):
        device_ids = select_device_ids(
            """
            SELECT owner.device_id
              FROM operations.computer_client_ownership owner
              JOIN operations.devices device
                ON device.tenant_id = owner.tenant_id AND device.id = owner.device_id
               AND device.deleted_at IS NULL
             WHERE owner.tenant_id = %s AND owner.state = 'dirty'
             ORDER BY owner.device_id LIMIT %s
            """,
            (tenant_id, batch_size),
        )
        if not device_ids:
            return counts
        project_each(device_ids)
    raise RuntimeError("Computer client ownership remains dirty after 100 reconciliation batches")
