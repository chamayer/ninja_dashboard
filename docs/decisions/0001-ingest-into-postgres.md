# 0001 — Ingest source data into Postgres

Status: Accepted
Date: Existing design; recorded 2026-07-16

## Context

Live dashboard queries against the source API would provide no durable history,
would inherit source latency and outages, and would complicate joins and
aggregation.

## Decision

Collect source data on a schedule and store current and historical state in
Postgres.

## Rationale

Local storage enables trends, indexing, reproducible queries, cross-domain
joins, and dashboard availability during upstream outages.

## Consequences

- Ingest freshness and health must be visible.
- Schema migrations and retention become operational responsibilities.
- Raw payloads should be retained where unmodeled fields may matter.
