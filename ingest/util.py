"""Small helpers shared across ingest modules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def ninja_epoch_to_dt(value: Any) -> datetime | None:
    """Convert a Ninja unix epoch (seconds, possibly fractional) to UTC
    datetime. None/0/missing → None."""
    if value is None or value == 0:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def content_hash(*values: Any) -> str:
    """Stable SHA-256 hex digest of pipe-joined stringified values.
    Used by SCD-2 tables to detect content changes."""
    parts = ["" if v is None else str(v) for v in values]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
