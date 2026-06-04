"""Custom fields ingest.

Source: GET /v2/queries/scoped-custom-fields (paginate_cursor)

The scoped Ninja response returns entity records of the shape:
    {"scope": "NODE|ORGANIZATION|LOCATION",
     "entityId": 123,
     "fields": {"warrantyExpiration": "...", "department": "..."}}

We keep the allowlisted field names only, upsert them into
`ninja_core.custom_field_values`, and regenerate pivoted views per
entity type so Metabase sees real columns
(`warranty_expiration`, `department`, ...) on
`ninja_core.v_device_custom_fields`,
`ninja_core.v_organization_custom_fields`, and
`ninja_core.v_location_custom_fields`.
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

_SCOPES = "NODE,ORGANIZATION,LOCATION"


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

        query_params: dict[str, Any] = {"scopes": _SCOPES}
        if allowlist:
            query_params["fields"] = ",".join(sorted(allowlist))

        value_rows: list[dict[str, Any]] = []
        observed: dict[tuple[str, str], dict[str, Any]] = {}

        for rec in client.paginate_cursor(
            "/queries/scoped-custom-fields",
            params=query_params,
        ):
            entity_id = rec.get("entityId")
            entity_type = _ENTITY_TYPE_BY_SCOPE.get(
                str(rec.get("entityType") or rec.get("scope") or "DEVICE").upper()
            )
            if entity_type is None:
                continue
            if entity_id is None:
                continue

            fields = rec.get("fields")
            if not isinstance(fields, dict):
                continue

            for fname, fvalue in fields.items():
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
            "Custom fields: %d values kept across %d distinct fields",
            len(value_rows), len(observed),
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
    """DROP + CREATE v_<entity>_custom_fields per scope.

    Each known field becomes a column via MAX(value_text) FILTER (...)
    over the SCD-2 history. If a scope has no fields in the current
    allowlist, keep the view present with just `entity_id` so Metabase
    relationships do not disappear.
    """
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for d in defs:
        by_scope.setdefault(d["scope"], []).append(d)

    for entity_type in ("DEVICE", "ORGANIZATION", "LOCATION"):
        view_name = f"v_{entity_type.lower()}_custom_fields"
        cur.execute(f"DROP VIEW IF EXISTS ninja_core.{view_name}")

        select_parts = ["entity_id"]
        fields = by_scope.get(entity_type, [])
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
