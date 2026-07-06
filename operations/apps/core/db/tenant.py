from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from django.db import connection, transaction

DEFAULT_TENANT_ID = 1


def set_local_tenant(tenant_id: int) -> None:
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = %s", [tenant_id])


def current_tenant_id() -> int | None:
    if connection.vendor != "postgresql":
        return None

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('operations.tenant_id', TRUE)")
        value = cursor.fetchone()[0]
    return int(value) if value else None


@contextmanager
def tenant_context(tenant_id: int) -> Iterator[None]:
    with transaction.atomic():
        set_local_tenant(tenant_id)
        yield


def client_scoped_query(
    request: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[tuple[Any, ...]]:
    current_client = getattr(request, "current_client", None)
    if current_client is None:
        raise ValueError("client_scoped_query requires request.current_client")

    query_params = [*(params or ()), current_client.id]
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM ({sql}) scoped_query WHERE client_id = %s", query_params)
        return list(cursor.fetchall())


def all_clients_query(
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or ())
        return list(cursor.fetchall())


class TenantGUCAssertionWrapper:
    def __call__(self, execute, sql, params, many, context):
        if connection.vendor != "postgresql":
            return execute(sql, params, many, context)

        normalized = sql.strip().lower()
        if normalized.startswith(("set ", "show ", "select current_setting")):
            return execute(sql, params, many, context)

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('operations.tenant_id', TRUE)")
            value = cursor.fetchone()[0]
        if not value:
            raise RuntimeError("operations.tenant_id is not set for this query")

        return execute(sql, params, many, context)
