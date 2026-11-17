# 0059 — Maintained Coverage selection

Status: Accepted direction; implementation candidate, not serving
Date: 2026-11-17
Plan: PLAN-056

Coverage selection uses domain-owned maintained Computer and platform facts,
not request-time source joins. Migration 0422 defines tenant-isolated tables,
indexes, a single protected publication writer and revision invalidation hooks.
The existing Jobs scheduler admits initial, invalidated and expired generations;
failed transactions preserve the previous publication and remain due for retry.
Readers distinguish missing, input-changed, policy-changed and expired results
from completed empty results. No GET refresh or expensive fallback is allowed.

The candidate rebuilds a tenant generation atomically. Source changes fence
publication through a transactional revision; refresh wrappers invalidate after
presence/session materialized-view refresh. Time boundaries and a sixty-second
maximum age expire a generation. Schema currently restricts publication to
tenant 1, matching the application. Existing protected inputs remain authority.

Cutover requires PostgreSQL migration/rollback, role/access, concurrent-change,
maintenance and output-parity validation plus full-request timing. Statement
invalidation uses a shared revision row: write contention and invalidation
frequency require review before deployment. No performance success is claimed.

Full-response adapter evidence: four maintained input queries through the current
Django view/templates measured 3.309 seconds versus 4.144 baseline with identical
CSRF-masked HTML. Original Hudu inventory is retained because prepared record
ordering differed. Existing Python fleet preparation also remains. This is an
isolated compatibility adapter, not completed bounded-page cutover or acceptance.
Publication now includes contacts, observation flags, requirement evaluation
timestamps and Hudu observation metadata needed by page consumers. Detailed
scope and limitations: root records/PLAN-056-coverage-reader-remediation.md.
