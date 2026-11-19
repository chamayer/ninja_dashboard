"""Keep Coverage publications until their inputs change."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations

_original = import_module(
    "apps.core.migrations.0422_coverage_maintained_read_model"
).FORWARD_SQL
_start = _original.index("CREATE FUNCTION operations.refresh_coverage_read(")
_end = _original.index("\nALTER FUNCTION operations.refresh_coverage_read", _start)
_function = _original[_start:_end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
_old_start = "least(v_at + interval '60 seconds', coalesce(("
_old_end = ") deadlines WHERE boundary > v_at), v_at + interval '60 seconds')), p_days,"
if _function.count(_old_start) != 1 or _function.count(_old_end) != 1:
    raise RuntimeError("Unexpected Coverage publication function")
_expiry_start = _function.index(_old_start)
_expiry_end = _function.index(_old_end, _expiry_start) + len(_old_end)
FORWARD_SQL = _function[:_expiry_start] + "'infinity'::timestamptz, p_days," + _function[_expiry_end:]
REVERSE_SQL = _function


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [("operations", "0424_coverage_publication_input_access")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
