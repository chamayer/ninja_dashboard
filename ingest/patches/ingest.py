"""Patches ingest.

Sources:
  - GET /v2/queries/os-patch-installs   → INSTALLED, FAILED
  - GET /v2/queries/os-patches          → PENDING, APPROVED, REJECTED

Both feed ninja_patches.patch_facts; `status` distinguishes the source.

SCD-2 pattern (same as ninja_core.custom_field_values):
  1. Compute content_hash from (status, installed_at, severity, type,
     kb_number, name) — the user-visible "what state is this patch in"
     payload. Ninja's collection `timestamp` is excluded so it doesn't
     defeat dedup.
  2. INSERT ... ON CONFLICT (device_id, patch_uid, content_hash)
     DO UPDATE SET last_observed_at = EXCLUDED.last_observed_at,
                   ninja_observed_at = EXCLUDED.ninja_observed_at,
                   data = EXCLUDED.data.
  3. Status transitions (PENDING → APPROVED → INSTALLED) produce a new
     row per state, so the full transition history is preserved.

Future: incremental mode using installedBefore/installedAfter query
params on /queries/os-patch-installs (TODO.md backlog).
"""

from datetime import datetime

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (rows_changed, rows_observed).
    `rows_changed` counts only inserts (new content_hash). `rows_observed`
    counts every (device, patch) pair seen — including unchanged ones
    whose last_observed_at was bumped."""
    raise NotImplementedError
