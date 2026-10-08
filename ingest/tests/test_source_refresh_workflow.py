"""Source-refresh successor signals stay aligned with the registry contract."""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

from ingest.intel.material import MaterialCount

# This focused routing test never connects.  The module import still builds the
# production settings object, so provide inert values before importing it.
for _name, _value in {
    "NINJA_BASE_URL": "https://example.invalid",
    "NINJA_TOKEN_URL": "https://example.invalid/token",
    "NINJA_CLIENT_ID": "test",
    "NINJA_CLIENT_SECRET": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
}.items():
    os.environ.setdefault(_name, _value)

from ingest import operator_job_queue


def _progress() -> SimpleNamespace:
    return SimpleNamespace(job_id=uuid4(), claim_token=uuid4(), update=lambda *_args: None)


def test_ninja_source_refresh_starts_patch_and_identity_follow_up(monkeypatch):
    binding_id = uuid4()
    monkeypatch.setattr(operator_job_queue, "_source_refresh_binding", lambda *_args: binding_id)
    monkeypatch.setattr(
        "ingest.sources.load_source_binding",
        lambda _binding_id: SimpleNamespace(platform="Ninja", source_name="Ninja", source_key=""),
    )
    monkeypatch.setattr("ingest.main.run_patching_once", lambda: True)

    result = operator_job_queue._run_source_refresh(_progress())

    assert result.rows is None
    assert result.signals == ("ninja_source", "identity_source")
    assert result.result == {"source_refresh": {"binding_id": str(binding_id)}}


def test_vulnerability_reference_refresh_starts_matching_only_on_material_change(monkeypatch):
    binding_id = uuid4()
    monkeypatch.setattr(operator_job_queue, "_source_refresh_binding", lambda *_args: binding_id)
    monkeypatch.setattr(
        "ingest.sources.load_source_binding",
        lambda _binding_id: SimpleNamespace(
            platform="reference.nvd", source_name="NVD", source_key="reference.nvd"
        ),
    )
    monkeypatch.setattr("ingest.intel.nvd.run_once", lambda: MaterialCount(4, material_changed=True))

    result = operator_job_queue._run_source_refresh(_progress())

    assert result.rows == 4
    assert result.signals == ("reference_match_data",)


def test_software_reference_refresh_starts_targeted_analysis_only_on_material_change(monkeypatch):
    binding_id = uuid4()
    monkeypatch.setattr(operator_job_queue, "_source_refresh_binding", lambda *_args: binding_id)
    monkeypatch.setattr(
        "ingest.sources.load_source_binding",
        lambda _binding_id: SimpleNamespace(
            platform="reference.winget", source_name="Windows Package Manager", source_key="reference.winget"
        ),
    )
    monkeypatch.setattr("ingest.intel.winget.run_once", lambda: MaterialCount(0, material_changed=False))

    unchanged = operator_job_queue._run_source_refresh(_progress())

    monkeypatch.setattr("ingest.intel.winget.run_once", lambda: MaterialCount(3, material_changed=True))
    changed = operator_job_queue._run_source_refresh(_progress())

    assert unchanged.signals == ()
    assert changed.rows == 3
    assert changed.signals == ("reference_software_data",)
