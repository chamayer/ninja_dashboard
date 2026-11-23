"""Read current Software Installations from the source-owned projection."""

from django.db import connection, transaction

from shared.software_coverage import EFFECTIVE_DECISION_JOINS, PUBLISHER_DECISION, TITLE_DECISION

_INSTALLATION_FROM = """
      FROM operations.v_current_source_installations i
      JOIN operations.devices d ON d.tenant_id = i.tenant_id AND d.id = i.device_id
      JOIN operations.clients c ON c.tenant_id = i.tenant_id AND c.id = i.client_id
     WHERE i.tenant_id = 1 AND i.stale_since IS NULL
"""

INSTALLATION_ROWS_SQL = f"""
    SELECT i.tenant_id, i.client_id, i.device_id, i.canonical_name, i.display_name,
           i.publisher, i.version, i.install_date, i.install_location, i.last_observed_at,
           d.canonical_hostname, d.canonical_serial, c.slug, c.display_name AS client_display_name
    {_INSTALLATION_FROM}
"""

_PAGE_ORDER = "i.client_display_name, i.canonical_hostname, i.canonical_name, i.device_id"


def _read_published_first_page(cursor):
    cursor.execute(
        "SELECT to_regprocedure('operations.read_software_installations_first_page(bigint)') IS NOT NULL"
    )
    if not cursor.fetchone()[0]:
        return []
    cursor.execute(
        f"""
        SELECT i.client_display_name, i.slug, i.device_id, i.canonical_hostname,
               i.canonical_name, coalesce(nullif(i.display_name, ''), i.canonical_name),
               i.publisher, i.version, i.install_date, i.install_location, i.last_observed_at,
               {TITLE_DECISION}, {PUBLISHER_DECISION}, published.total,
               CASE WHEN row_number() OVER page_order = 1 THEN published.products END,
               CASE WHEN row_number() OVER page_order = 1 THEN published.publishers END,
               CASE WHEN row_number() OVER page_order = 1 THEN published.computers END
          FROM operations.read_software_installations_first_page(1) published
          LEFT JOIN LATERAL jsonb_to_recordset(published.page_rows) AS i(
              tenant_id bigint, client_id uuid, device_id uuid, client_display_name text,
              slug text, canonical_hostname text, canonical_name text, display_name text,
              publisher text, version text, install_date date, install_location text,
              last_observed_at timestamptz
          ) ON true
          {EFFECTIVE_DECISION_JOINS}
        WINDOW page_order AS (ORDER BY {_PAGE_ORDER})
         ORDER BY {_PAGE_ORDER}
        """
    )
    return cursor.fetchall()


def _page_result(result):
    # A left join to the page retains totals and choices even for zero matches.
    first = result[0]
    return first[13], [row[:13] for row in result if row[2] is not None], *first[14:]


def read_page(clauses, params, *, filter_by_decision: bool, page: int, page_size: int):
    """Read exact totals, a clamped page and facet options from one inventory snapshot."""
    filter_joins = EFFECTIVE_DECISION_JOINS if filter_by_decision else ""
    matching_storage = "MATERIALIZED" if filter_by_decision else "NOT MATERIALIZED"
    where_sql = " AND ".join(clauses) or "TRUE"
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL operations.tenant_id = 1")
        if not clauses and page == 1 and page_size == 100:
            published = _read_published_first_page(cursor)
            if published:
                return _page_result(published)
        cursor.execute(
            f"""
            WITH inventory AS MATERIALIZED (
                SELECT i.tenant_id, i.client_id, i.device_id, i.source_record_id,
                       i.canonical_name, i.display_name, i.publisher, i.last_observed_at,
                       d.canonical_hostname, c.slug, c.display_name AS client_display_name
                {_INSTALLATION_FROM}
            ), matching AS {matching_storage} (
                SELECT i.*
                  FROM inventory i
                  {filter_joins}
                 WHERE {where_sql}
            ), totals AS (
                SELECT count(*) AS total FROM matching
            ), page AS (
                SELECT i.*
                  FROM matching i
                 ORDER BY {_PAGE_ORDER}
                 LIMIT %s
                OFFSET (SELECT least(%s, greatest(0, (total - 1) / %s)) * %s FROM totals)
            ), latest_products AS (
                SELECT canonical_name, max(last_observed_at) AS last_observed_at
                  FROM inventory
                 GROUP BY canonical_name
            ), choices AS (
                SELECT ARRAY(
                    SELECT ARRAY[product.canonical_name,
                                 coalesce(nullif(min(i.display_name), ''), product.canonical_name)]
                      FROM latest_products product
                      JOIN inventory i USING (canonical_name, last_observed_at)
                     GROUP BY product.canonical_name
                     ORDER BY product.canonical_name
                ) AS products,
                ARRAY(
                    SELECT DISTINCT publisher FROM inventory WHERE publisher <> '' ORDER BY publisher
                ) AS publishers,
                ARRAY(
                    SELECT ARRAY[client_display_name, canonical_hostname, device_id::text]
                      FROM (
                          SELECT DISTINCT device_id, canonical_hostname, client_display_name FROM inventory
                      ) current_computers
                     ORDER BY 1
                ) AS computers
            )
            SELECT i.client_display_name, i.slug, i.device_id, i.canonical_hostname,
                   i.canonical_name, coalesce(nullif(i.display_name, ''), i.canonical_name),
                   i.publisher, detail.version, detail.install_date, detail.install_location, i.last_observed_at,
                   {TITLE_DECISION}, {PUBLISHER_DECISION}, totals.total,
                   CASE WHEN row_number() OVER page_order = 1 THEN choices.products END,
                   CASE WHEN row_number() OVER page_order = 1 THEN choices.publishers END,
                   CASE WHEN row_number() OVER page_order = 1 THEN choices.computers END
              FROM totals CROSS JOIN choices LEFT JOIN page i ON true
              LEFT JOIN operations.source_record_software_current detail
                ON detail.tenant_id = i.tenant_id AND detail.source_record_id = i.source_record_id
               AND detail.canonical_name = i.canonical_name
              {EFFECTIVE_DECISION_JOINS}
            WINDOW page_order AS (ORDER BY {_PAGE_ORDER})
             ORDER BY {_PAGE_ORDER}
            """,
            [*params, page_size, min(page - 1, 2**63 - 1), page_size, page_size],
        )
        result = cursor.fetchall()
    return _page_result(result)
