"""Custom fields ingest.

Sources:
  - GET /v2/queries/custom-fields-detailed  (definitions: name, scope, type, ...)
  - GET /v2/queries/custom-fields           (values per entity)

Targets:
  - ninja_core.custom_field_definitions  (upsert on id)
  - ninja_core.custom_field_values       (SCD-2; see below)

SCD-2 on values: insert new row when content_hash differs,
otherwise advance last_observed_at on the existing row.

Side effect: regenerates pivoted views (`v_device_custom_fields`,
`v_organization_custom_fields`, `v_location_custom_fields`) from the
current set of definitions. Each known field becomes a real column
visible in Metabase.

NOTE: the Ninja API response shape for these two endpoints wasn't in
the OpenAPI extract used to design the schema. The mapping below is a
best-guess using Ninja's standard conventions; iterate if the live
shape differs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg.types.json import Json

from ingest import db
from ingest.ninja_client import NinjaClient
from ingest.runlog import run_log
from ingest.util import content_hash, ninja_epoch_to_dt

log = logging.getLogger(__name__)

_ENTITY_TYPE_BY_SCOPE = {
    "DEVICE":       "DEVICE",
    "NODE":         "DEVICE",
    "ORGANIZATION": "ORGANIZATION",
    "LOCATION":     "LOCATION",
}


def run(client: NinjaClient, snapshot_at: datetime) -> tuple[int, int]:
    """Returns (definitions_upserted, values_changed)."""
    with run_log("core.custom_fields") as stats:
        def_rows = _fetch_definitions(client)
        val_rows = _fetch_values(client)

        with db.transaction() as cur:
            def_count = (
                db.upsert(
                    cur,
                    "ninja_core.custom_field_definitions",
                    def_rows,
                    conflict_keys=["id"],
                )
                if def_rows else 0
            )

            for row in val_rows:
                row["first_observed_at"] = snapshot_at
                row["last_observed_at"] = snapshot_at

            val_count = (
                db.upsert(
                    cur,
                    "ninja_core.custom_field_values",
                    val_rows,
                    conflict_keys=[
                        "entity_type", "entity_id", "field_name", "content_hash",
                    ],
                    update_cols=["last_observed_at"],
                )
                if val_rows else 0
            )

            _regenerate_pivoted_views(cur, def_rows)

        stats["rows_upserted"] = def_count
        stats["rows_inserted"] = val_count
        log.info(
            "definitions: %d upserted; values: %d observed",
            def_count, len(val_rows),
        )
        return def_count, val_count


def _fetch_definitions(client: NinjaClient) -> list[dict[str, Any]]:
    """Pull definitions from /queries/custom-fields-detailed.
    Response is expected to be either a flat list or {results: [...]}.
    """
    resp = client.get("/queries/custom-fields-detailed")
    raw = resp.get("results") if isinstance(resp, dict) else resp
    raw = raw or []
    log.info("Fetched %d custom field definitions", len(raw))
    rows: list[dict[str, Any]] = []
    for d in raw:
        if "id" not in d or "name" not in d:
            log.warning("Skipping definition without id/name: keys=%s",
                        list(d.keys()))
            continue
        rows.append({
            "id":         d["id"],
            "name":       d["name"],
            "label":      d.get("label") or d.get("displayName"),
            "scope":      d.get("scope", "DEVICE"),
            "field_type": d.get("type") or d.get("fieldType", "TEXT"),
            "data":       Json(d),
        })
    return rows


def _fetch_values(client: NinjaClient) -> list[dict[str, Any]]:
    """Pull values from /queries/custom-fields. Tolerant of two common
    shapes: flat list of {nodeId/entityId, fieldName, value, ...} or
    {results: [...]}."""
    resp = client.get("/queries/custom-fields")
    raw = resp.get("results") if isinstance(resp, dict) else resp
    raw = raw or []
    log.info("Fetched %d raw custom field value records", len(raw))

    rows: list[dict[str, Any]] = []
    for r in raw:
        # Two possible shapes: per-field record OR per-entity record
        # with a "fields" dict.
        if "fields" in r and isinstance(r["fields"], dict):
            entity_id = r.get("nodeId") or r.get("entityId") or r.get("id")
            entity_type = _ENTITY_TYPE_BY_SCOPE.get(
                str(r.get("scope") or r.get("entityType") or "DEVICE").upper(),
                "DEVICE",
            )
            for fname, fvalue in r["fields"].items():
                rows.append(_value_row(entity_type, entity_id, fname, fvalue))
        else:
            entity_id = (
                r.get("nodeId") or r.get("entityId") or r.get("deviceId")
            )
            entity_type = _ENTITY_TYPE_BY_SCOPE.get(
                str(r.get("scope") or r.get("entityType") or "DEVICE").upper(),
                "DEVICE",
            )
            fname = r.get("name") or r.get("fieldName")
            if fname is None or entity_id is None:
                continue
            rows.append(_value_row(
                entity_type, entity_id, fname, r.get("value"),
            ))
    return rows


def _value_row(
    entity_type: str,
    entity_id: int,
    field_name: str,
    value: Any,
) -> dict[str, Any]:
    value_text, value_number, value_date, value_bool = _split_value(value)
    h = content_hash(value_text, value_number, value_date, value_bool, value)
    return {
        "entity_type":  entity_type,
        "entity_id":    int(entity_id),
        "field_name":   field_name,
        "value_text":   value_text,
        "value_number": value_number,
        "value_date":   value_date,
        "value_bool":   value_bool,
        "raw_value":    Json(value),
        "content_hash": h,
    }


def _split_value(value: Any) -> tuple[
    str | None, Decimal | None, datetime | None, bool | None,
]:
    """Best-effort typed-column population.
    Numeric/boolean/date go into their typed columns; everything also
    lands in value_text for display."""
    if value is None:
        return None, None, None, None
    if isinstance(value, bool):
        return str(value), None, None, value
    if isinstance(value, (int, float)):
        try:
            return str(value), Decimal(str(value)), None, None
        except InvalidOperation:
            return str(value), None, None, None
    if isinstance(value, str):
        # Try Ninja epoch (numeric string)
        try:
            num = Decimal(value)
            return value, num, None, None
        except (InvalidOperation, ValueError):
            return value, None, None, None
    # objects, lists — text-only
    return str(value), None, None, None


def _regenerate_pivoted_views(cur: Any, def_rows: list[dict]) -> None:
    """Drop & recreate v_<entity>_custom_fields views from the current
    definitions. Each known field name becomes a column via
    `MAX(value_*) FILTER (WHERE field_name = '<n>')` on the latest
    last_observed_at per (entity, field) pair."""
    by_scope: dict[str, list[dict]] = {}
    for d in def_rows:
        scope = d["scope"]
        entity_type = _ENTITY_TYPE_BY_SCOPE.get(str(scope).upper())
        if entity_type is None:
            continue
        by_scope.setdefault(entity_type, []).append(d)

    for entity_type, defs in by_scope.items():
        view_name = f"v_{entity_type.lower()}_custom_fields"
        cur.execute(f"DROP VIEW IF EXISTS ninja_core.{view_name}")
        if not defs:
            continue

        select_parts = ["entity_id", "MAX(last_observed_at) AS last_observed_at"]
        for d in defs:
            col_name = _safe_col_name(d["name"])
            field_name = d["name"].replace("'", "''")
            col = _typed_filter_expr(d["field_type"], field_name)
            select_parts.append(f"{col} AS {col_name}")

        view_sql = (
            f"CREATE OR REPLACE VIEW ninja_core.{view_name} AS "
            f"SELECT {', '.join(select_parts)} "
            f"FROM ninja_core.custom_field_values "
            f"WHERE entity_type = '{entity_type}' "
            f"GROUP BY entity_id"
        )
        cur.execute(view_sql)
        log.info("Regenerated view ninja_core.%s (%d fields)",
                 view_name, len(defs))


def _typed_filter_expr(field_type: str | None, field_name: str) -> str:
    ft = (field_type or "TEXT").upper()
    if ft in {"NUMERIC", "INTEGER", "DECIMAL"}:
        col = "value_number"
    elif ft in {"DATE", "DATETIME", "TIMESTAMP"}:
        col = "value_date"
    elif ft in {"CHECKBOX", "BOOLEAN", "BOOL"}:
        col = "value_bool"
    else:
        col = "value_text"
    return (
        f"MAX({col}) FILTER (WHERE field_name = '{field_name}')"
    )


def _safe_col_name(name: str) -> str:
    """Sanitize a Ninja custom-field name into a SQL-safe column ident.
    Lowercases, keeps alphanumerics and underscores; everything else
    becomes underscore. Prefixes with `cf_` if starts with a digit."""
    safe = "".join(
        c.lower() if c.isalnum() else "_" for c in name
    )
    if safe and safe[0].isdigit():
        safe = "cf_" + safe
    return safe or "cf_unnamed"
