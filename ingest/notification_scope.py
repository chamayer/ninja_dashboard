"""Shared SQL predicate for which finding types may notify at all."""

from __future__ import annotations


def alertable_clause(type_id_expr: str) -> str:
    """Return a predicate that is true only for types flagged ``alertable``.

    ``alertable`` is registry data on ``operations.finding_types`` (default
    false). It only permits a notification (alert or digest line); routes and
    rules still decide where it goes.
    """
    return f"""
                   AND EXISTS (
                       SELECT 1
                         FROM operations.finding_types alertable_type
                        WHERE alertable_type.id = {type_id_expr}
                          AND alertable_type.alertable IS TRUE
                   )"""
