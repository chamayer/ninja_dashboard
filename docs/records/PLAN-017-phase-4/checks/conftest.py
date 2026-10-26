"""Phase 4 prototypes reuse the Phase 2 disposable PostgreSQL fixtures.

Run from the repository root:

    RUN_POSTGRES_INTEGRATION_TESTS=1 .venv/Scripts/python.exe -m pytest \
        -p no:cacheprovider docs/records/PLAN-017-phase-4/checks -q

A prototype applies a *candidate* design to copies of current SQL inside a
disposable database. Nothing here changes repository source or a migration.
"""

from __future__ import annotations

import importlib.util
import pathlib

_PHASE2 = pathlib.Path(__file__).resolve().parents[2] / "PLAN-017-phase-2/checks/conftest.py"
_spec = importlib.util.spec_from_file_location("plan017_phase2_conftest", _PHASE2)
phase2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phase2)

postgres_dsn = phase2.postgres_dsn
