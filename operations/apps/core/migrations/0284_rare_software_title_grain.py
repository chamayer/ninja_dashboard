"""Raise rare software per title instead of per device (design D15, D16).

Rare software is undecided software installed on at most the rare limit of
devices, at any age; recency only raises its severity. One finding per title
names the software, and the affected devices are the exposure join, like every
other title-level software fact. The reconcile resolves the previous per-device
findings with the reason ``subject_regrained`` when it opens the title-level
ones.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
UPDATE operations.finding_types
   SET subject_scope = 'software_product'
 WHERE name = 'rare_recent';
"""

REVERSE_SQL = r"""
UPDATE operations.finding_types
   SET subject_scope = 'device'
 WHERE name = 'rare_recent';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0283_software_rules_and_finding_type_policy"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
