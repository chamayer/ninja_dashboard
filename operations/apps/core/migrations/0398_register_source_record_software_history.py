"""Classify the per-source software tables in the change-history registry.

0376 (PLAN-036) added ``source_record_software_current`` and its interval history
``source_record_software_history`` without registering them, so a
``change_history_unclassified`` Issue has been open for each since 2026-11-01.
The pair follows the observation precedent: the current table keeps its own
history, and the history table is a history store.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
INSERT INTO operations.change_history_registry (
    table_name, classification, reason, recorded_columns, secret_columns, key_columns,
    computer_column, computer_condition_column, computer_condition_value, client_column,
    is_global, capture
) VALUES
    ('source_record_software_current', 'own_history',
     'per-source software inventory; intervals in source_record_software_history',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL),
    ('source_record_software_history', 'history_store',
     'interval history of source_record_software_current',
     '{}'::text[], '{}'::text[], '{}'::text[], NULL, NULL, NULL, NULL, FALSE, NULL)
ON CONFLICT (table_name) DO NOTHING;
"""

REVERSE_SQL = r"""
DELETE FROM operations.change_history_registry
 WHERE table_name IN ('source_record_software_current', 'source_record_software_history');
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0397_source_record_companions"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
