"""The projected Computer name matches ingest.normalize.normalize_hostname (ADR-0032)."""

from __future__ import annotations

import os
import re

import psycopg
import pytest

from ingest.device_cache_projector import MACHINE_NAME_RE, NORMALIZED_HOSTNAME_SQL
from ingest.normalize import normalize_hostname

SAMPLES = [
    "LAB117-41",
    "VMWare12.utaw.org",
    "Charlies-Mac-mini.local",
    "Server2 (Retired #65268)",
    "Yidel's computer Retired #117472",
    "RDAPP14_Retired (#120237)",
    "localhost.localdomain",
    "  PC-01 ",
    "DellData migrated?",
]


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 for PostgreSQL coverage")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        with psycopg.connect(dsn, autocommit=True) as connection:
            yield connection


@pytest.mark.parametrize("raw", SAMPLES)
def test_sql_normalization_matches_python(conn, raw):
    sql = NORMALIZED_HOSTNAME_SQL.format(value="%s::text")
    assert conn.execute(f"SELECT {sql}", (raw,)).fetchone()[0] == normalize_hostname(raw)


def test_only_machine_names_are_projected():
    names = {raw: normalize_hostname(raw) for raw in SAMPLES}
    projected = {raw for raw, name in names.items() if re.match(MACHINE_NAME_RE, name)}
    assert "Yidel's computer Retired #117472" not in projected
    assert "DellData migrated?" not in projected
    assert {"LAB117-41", "VMWare12.utaw.org", "Server2 (Retired #65268)"} <= projected
