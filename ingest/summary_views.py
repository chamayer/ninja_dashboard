"""Refresh shared materialized dashboard summary views."""

from __future__ import annotations

import logging

import psycopg

from ingest import db

log = logging.getLogger(__name__)


def refresh_device_troubleshooting_signal() -> None:
    try:
        with db.transaction() as cur:
            cur.execute(
                "REFRESH MATERIALIZED VIEW ninja_core.device_troubleshooting_signal"
            )
        log.info("Refreshed materialized view ninja_core.device_troubleshooting_signal")
    except (psycopg.errors.UndefinedTable, psycopg.errors.WrongObjectType):
        log.info(
            "ninja_core.device_troubleshooting_signal is not materialized yet; "
            "skipping refresh"
        )
