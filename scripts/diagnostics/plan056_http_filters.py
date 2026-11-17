"""Item 5: four fixed filter variants using the reviewed HTTP matrix engine."""

from __future__ import annotations

import hashlib
from pathlib import Path

import plan056_http_matrix as matrix
from plan056_http_pilot import emit, main


EXPECTED = {
    "views.py": "8701f537683df51e24b0eb7e6d15c945aacd44c3b5d5deea01ca891c7e8927c5",
    "context_processors.py": "b28231551515f1bae15d679950433dd819603895ee6bf92037a60e346b32d7b4",
}
ROUTES = (
    "/devices/?os=Windows",
    "/inventory/source-records/?type=agent.rmm",
    "/patching/?role=server",
    "/software/?safety=high",
)


def run() -> int:
    for name, expected in EXPECTED.items():
        actual = hashlib.sha256(
            (Path("/app/apps/core") / name).read_bytes()
        ).hexdigest()
        if actual != expected:
            emit("source_gate_failed", module=name, reason="hash_mismatch")
            return 1
    matrix.ROUTES = ROUTES
    matrix.STOP = Path("/tmp/plan056-item5-stop")
    emit("filter_scope", variants=4, max_gets=8, coverage_excluded=True)
    return main(matrix.measure)


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
