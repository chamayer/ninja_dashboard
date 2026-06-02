"""Custom fields ingest.

Source: GET /v2/queries/custom-fields  (paginate_cursor)

The actual Ninja response is per-device records of the shape:
    {"deviceId": 123, "entityType": "DEVICE",
     "fields": {"warrantyExpiration": "...", "department": "..."}}

NOT separate definitions/values endpoints. We derive definitions from
the field names observed in the values, then regenerate pivoted views
per entity type so Metabase sees real columns (`warranty_expiration`,
`department`, ...) on `ninja_core.v_device_custom_fields`.

Targets:
  - ninja_core.custom_field_values  (SCD-2 — insert on hash change,
    advance last_observed_at on duplicate)
  - ninja_core.v_<entity>_custom_fields  (pivoted views, regenerated)

The custom_field_definitions table is NOT populated in v0.1 — its
columns need source data (id, label, type) that the /custom-fields
endpoint doesn't return at this depth. Tracked in TODO as a
follow-up (probably needs /custom-fields-detailed once we know its
real shape, or a different endpoint).
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.config import settings
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import content_hash

log = logging.getLogger(__name__)

_ENTITY_TYPE_BY_SCOPE = {
    "DEVICE":       "DEVICE",
    "NODE":         "DEVICE",
    "ORGANIZATION": "ORGANIZATION",
    "LOCATION":     "LOCATION",
}


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (values_observed, distinct_fields_seen)."""
    with run_log("core.custom_fields") as stats:
        allowlist = settings.custom_fields_include
        max_text = settings.INGEST_CUSTOM_FIELDS_MAX_TEXT
        if not allowlist:
            log.warning(
                "INGEST_CUSTOM_FIELDS_INCLUDE is empty — ingesting ALL custom "
                "fields. Set the env var to a comma-separated allowlist of "
                "field names to keep just what your dashboards use.",
            )
        else:
            log.info("Allowlist: %s", sorted(allowlist))

        value_rows: list[dict[str, Any]] = []
        observed: dict[tuple[str, str], dict[str, Any]] = {}
        skipped_by_allowlist = 0

        for rec in client.paginate_cursor("/queries/custom-fields"):
            entity_id = (
                rec.get("deviceId")
                or rec.get("nodeId")
                or rec.get("entityId")
            )
            entity_type = _ENTITY_TYPE_BY_SCOPE.get(
                str(rec.get("entityType") or rec.get("scope") or "DEVICE").upper(),
                "DEVICE",
            )
            if entity_id is None:
                continue

            fields = rec.get("fields")
            if not isinstance(fields, dict):
                continue

            for fname, fvalue in fields.items():
                if allowlist and fname not in allowlist:
                    skipped_by_allowlist += 1
                    continue

                # Some Ninja endpoints wrap values; tolerate either shape.
                if isinstance(fvalue, dict) and "value" in fvalue:
                    actual_value = fvalue.get("value")
                else:
                    actual_value = fvalue

                value_rows.append(_value_row(
                    entity_type, int(entity_id), fname, actual_value,
                    snapshot_at, max_text,
                ))
                observed.setdefault((entity_type, fname), {
                    "scope":      entity_type,
                    "name":       fname,
                    "field_type": "TEXT",
                })

        log.info(
            "Custom fields: %d values kept across %d distinct fields "
            "(%d field-occurrences skipped by allowlist)",
            len(value_rows), len(observed), skipped_by_allowlist,
        )

        with db.transaction() as cur:
            val_count = (
                db.upsert(
                    cur,
                    "ninja_core.custom_field_values",
                    value_rows,
                    conflict_keys=[
                        "entity_type", "entity_id", "field_name", "content_hash",
                    ],
                    update_cols=["last_observed_at"],
                )
                if value_rows else 0
            )
            _regenerate_pivoted_views(cur, list(observed.values()))

        stats["rows_inserted"] = val_count
        stats["rows_upserted"] = len(observed)
        return val_count, len(observed)


def _value_row(
    entity_type: str,
    entity_id: int,
    field_name: str,
    value: Any,
    snapshot_at: datetime,
    max_text: int,
) -> dict[str, Any]:
    value_text, value_number = _split_value(value)
    if value_text is not None and len(value_text) > max_text:
        original_len = len(value_text)
        value_text = (
            value_text[:max_text]
            + f"...[truncated, was {original_len} chars]"
        )
    h = content_hash(value_text, value_number, value)
    return {
        "entity_type":       entity_type,
        "entity_id":         entity_id,
        "field_name":        field_name,
        "value_text":        value_text,
        "value_number":      value_number,
        "value_date":        None,
        "value_bool":        value if isinstance(value, bool) else None,
        "raw_value":         Json(value),
        "content_hash":      h,
        "first_observed_at": snapshot_at,
        "last_observed_at":  snapshot_at,
    }


def _split_value(value: Any) -> tuple[str | None, Decimal | None]:
    """Pull a text + numeric representation. Anything stringifiable
    goes to value_text; numeric-looking strings/ints/floats also go
    to value_number for range filtering in Metabase."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return str(value), None
    if isinstance(value, (int, float)):
        try:
            return str(value), Decimal(str(value))
        except InvalidOperation:
            return str(value), None
    if isinstance(value, str):
        try:
            return value, Decimal(value)
        except (InvalidOperation, ValueError):
            return value, None
    return str(value), None


def _regenerate_pivoted_views(cur: Any, defs: list[dict[str, Any]]) -> None:
    """DROP + CREATE v_<entity>_custom_fields per scope. Each known
    field becomes a column via DISTINCT ON (entity, field) ordered by
    last_observed_at DESC. All columns currently `value_text` since
    we don't have type info from this endpoint."""
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for d in defs:
        by_scope.setdefault(d["scope"], []).append(d)

    for entity_type, fields in by_scope.items():
        view_name = f"v_{entity_type.lower()}_custom_fields"
        cur.execute(f"DROP VIEW IF EXISTS ninja_core.{view_name}")
        if not fields:
            continue

        select_parts = ["entity_id"]
        for d in fields:
            col_name = _safe_col_name(d["name"])
            field_name = d["name"].replace("'", "''")
            select_parts.append(
                f"MAX(value_text) FILTER "
                f"(WHERE field_name = '{field_name}') AS {col_name}"
            )

        cur.execute(
            f"CREATE OR REPLACE VIEW ninja_core.{view_name} AS "
            f"SELECT {', '.join(select_parts)} "
            f"FROM ninja_core.custom_field_values "
            f"WHERE entity_type = '{entity_type}' "
            f"GROUP BY entity_id"
        )
        log.info("Regenerated view ninja_core.%s (%d fields)",
                 view_name, len(fields))


def _safe_col_name(name: str) -> str:
    """Sanitize a field name into a SQL ident: lowercase alphanumerics +
    underscores. Prefixed with `cf_` if starting with a digit."""
    safe = "".join(c.lower() if c.isalnum() else "_" for c in name)
    if safe and safe[0].isdigit():
        safe = "cf_" + safe
    return safe or "cf_unnamed"
