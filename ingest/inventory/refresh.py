"""Refresh materialized Inventory current facts."""

from __future__ import annotations

import logging

import psycopg

from ingest import db

log = logging.getLogger(__name__)


def refresh_current() -> bool:
    """Refresh Inventory current facts if the materialized module exists."""
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT ninja_inventory.refresh_current()")
        log.info("Inventory current facts refreshed")
        return True
    except psycopg.errors.UndefinedFunction:
        log.info("Inventory refresh function not installed yet; skipping")
        return False
    except psycopg.errors.InvalidSchemaName:
        log.info("Inventory schema not installed yet; skipping refresh")
        return False
