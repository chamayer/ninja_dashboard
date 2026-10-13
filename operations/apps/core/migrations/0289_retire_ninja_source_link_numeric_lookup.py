"""Retire the unused source-link numeric lookup index.

The direct indexed join introduced with migration 0288 regressed the live
query plan.  User exposure retains its proven materialized canonical-link
join, which does not use that index.  Remove the unused access path rather
than leaving ongoing collection overhead for a failed optimization.
"""

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies: ClassVar = [
        ("operations", "0288_ninja_source_link_numeric_lookup"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            sql="""
            DROP INDEX CONCURRENTLY IF EXISTS operations.idx_entity_source_links_ninja_numeric;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
