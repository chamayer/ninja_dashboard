"""Activities domain — Ninja's built-in event log.

Cross-cutting enrichment source: a single endpoint feeds patch
context (apply started/completed, approvals, rollbacks) and, in future,
context for tickets / alerts / jobs / backups domains.

Filtered aggressively — see INGEST_ACTIVITY_SOURCES and
INGEST_ACTIVITY_TYPES_INCLUDE in .env.example.
"""
