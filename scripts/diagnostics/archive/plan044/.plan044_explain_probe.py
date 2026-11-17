import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.db import connection, transaction

from apps.core.issue_selection import Scope, _filtered_sql, mapping_types

sql, params = _filtered_sql(
    Scope(status="open_paused"), summary=True, home_compact=True
)
params["mapping_types"] = list(mapping_types())
statement = sql + """
SELECT type_name, issue_category, severity, status,
       count(*)::int, count(DISTINCT client_id)::int,
       (count(DISTINCT (subject_type, subject_id)) FILTER (WHERE subject_id IS NOT NULL)
        + count(*) FILTER (WHERE kind = 'candidate'))::int,
       MAX(CASE severity WHEN 'critical' THEN 5 WHEN 'high' THEN 4
           WHEN 'medium' THEN 3 WHEN 'low' THEN 2 ELSE 1 END)::int,
       GROUPING(severity)::int, GROUPING(type_name)::int,
       count(*) FILTER (WHERE status = 'open')::int,
       count(*) FILTER (WHERE status = 'paused')::int,
       count(*) FILTER (WHERE status = 'open' AND severity = 'critical')::int,
       count(*) FILTER (WHERE status = 'open' AND severity = 'critical'
           AND type_name = ANY(%(mapping_types)s))::int,
       count(DISTINCT client_id) FILTER (WHERE status = 'open' AND severity = 'critical'
           AND type_name = ANY(%(mapping_types)s))::int
  FROM selected
 GROUP BY GROUPING SETS (
     (type_name, issue_category, severity, status),
     (type_name, issue_category, status),
     ()
 )
"""
with transaction.atomic(), connection.cursor() as cursor:
    cursor.execute("SET LOCAL operations.tenant_id = 1")
    cursor.execute("EXPLAIN (FORMAT JSON) " + statement, params)
    plan = cursor.fetchone()[0][0]["Plan"]

def walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk(child)

for node in walk(plan):
    print(
        f"node={node['Node Type']} rel={node.get('Relation Name', '')} "
        f"index={node.get('Index Name', '')} rows={node.get('Plan Rows', '')} "
        f"width={node.get('Plan Width', '')} cost={node.get('Total Cost', '')} "
        f"subplan={node.get('Subplan Name', '')}"
    )
