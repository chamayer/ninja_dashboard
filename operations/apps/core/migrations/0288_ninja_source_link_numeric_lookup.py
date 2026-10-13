"""Index the canonical Ninja source-link lookup used by User exposure.

Ninja's source-owned device ID is text on the generic source-link relation,
while Ninja detail observations use an integer.  The Operations page needs a
safe conversion to join them.  This is an access path on the existing
canonical relation, not a second mapping or source-specific state store.
"""

from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    # entity_source_links changes while collectors run; avoid blocking them.
    atomic = False

    dependencies: ClassVar = [
        ("operations", "0287_jobs_progress_counts"),
    ]

    operations: ClassVar = [
        migrations.RunSQL(
            sql=r"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_source_links_ninja_numeric
                ON operations.entity_source_links (
                    tenant_id,
                    (
                        CASE
                            WHEN external_id ~ '^\d+$'
                             AND (
                                 length(external_id) < 10
                                 OR (
                                     length(external_id) = 10
                                     AND external_id <= '2147483647'
                                 )
                             )
                            THEN external_id::integer
                            ELSE NULL::integer
                        END
                    ),
                    source_instance_id
                )
                WHERE entity_class_id = 'device'
                  AND external_namespace NOT IN ('asset', 'device-health');
            """,
            reverse_sql="""
            DROP INDEX CONCURRENTLY IF EXISTS operations.idx_entity_source_links_ninja_numeric;
            """,
        ),
    ]
