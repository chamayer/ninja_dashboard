"""Sync policy allowlists used by active-device scope classification."""

from __future__ import annotations

import logging

from ingest import db
from ingest.config import settings
from ingest.runlog import run_log

log = logging.getLogger(__name__)


def sync_patching_enabled_policies() -> int:
    """Persist the env-driven server policy allowlist into Postgres."""
    values = sorted(settings.patching_enabled_policies)
    with run_log("policy_scope") as stats:
        with db.transaction() as cur:
            cur.execute("TRUNCATE ninja_core.patching_enabled_policies")
            if values:
                cur.executemany(
                    "INSERT INTO ninja_core.patching_enabled_policies (policy_name) VALUES (%s)",
                    [(value,) for value in values],
                )
        stats["rows_inserted"] = len(values)
        log.info("Synced %d patching-enabled policy names", len(values))
        return len(values)
