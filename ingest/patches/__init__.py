"""Patches domain — first ingest domain.

Sources two endpoints into a single fact table, distinguished by status:
  - /v2/queries/os-patch-installs  → INSTALLED, FAILED
  - /v2/queries/os-patches         → PENDING, APPROVED, REJECTED
"""
