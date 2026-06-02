"""Smoke test — verify env, DB, and Ninja API connectivity.

Usage:
    python -m ingest.smoke

Does not write to the database. Exits non-zero on any failure so it's
usable as a deployment sanity check.
"""

from __future__ import annotations

import logging
import sys

from ingest import db, migrations
from ingest.config import settings
from ingest.ninja_client import NinjaClient


def main() -> int:
    logging.basicConfig(
        level=settings.INGEST_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("smoke")

    # 1. Postgres connectivity
    log.info(
        "Postgres: %s@%s:%d/%s",
        settings.POSTGRES_USER,
        settings.POSTGRES_HOST,
        settings.POSTGRES_PORT,
        settings.POSTGRES_DB,
    )
    db.init(settings.postgres_dsn)
    with db.transaction() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    log.info("Postgres: OK")

    # 2. Migrations applied (idempotent — safe to run)
    applied = migrations.apply_pending()
    log.info("Migrations: %d pending applied", len(applied))

    # 3. Ninja API auth + one read
    log.info("Ninja API: %s", settings.NINJA_BASE_URL)
    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        orgs = client.get("/organizations")
        log.info("Ninja API: OK — %d organizations visible", len(orgs))

    log.info("Smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
