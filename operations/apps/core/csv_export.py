"""Reusable CSV-export helper for Operations list views.

Per the "every table should be exportable" rule (2026-07-20). Any
list view that renders a table can opt into a `?format=csv` branch
by calling `csv_response(rows, columns, filename_stem)` and returning
the result before its normal render path. Columns are declared as
`(header_label, key_or_getter)` tuples where the second element is
either a string field/dict key or a callable taking the row and
returning the value.

The helper writes UTF-8-BOM CSV so Excel opens it cleanly with
non-ASCII characters. Filename is timestamped so successive
downloads don't overwrite.

Usage:
```python
if request.GET.get("format") == "csv":
    return csv_response(
        rows,
        columns=[
            ("Hostname", "canonical_hostname"),
            ("Client", lambda r: r.client.display_name),
            ("Type", "device_type"),
        ],
        filename_stem="devices",
    )
```
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable
from datetime import datetime
from io import StringIO
from typing import Any

from django.http import HttpResponse

_ColumnGetter = str | Callable[[Any], Any]
Columns = list[tuple[str, _ColumnGetter]]


def _resolve(row: Any, getter: _ColumnGetter) -> Any:
    if callable(getter):
        return getter(row)
    # String getter: try dict access first, then attribute access.
    if isinstance(row, dict):
        return row.get(getter, "")
    return getattr(row, getter, "")


def _format(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def csv_response(
    rows: Iterable[Any],
    columns: Columns,
    filename_stem: str,
) -> HttpResponse:
    """Serialize rows to a CSV HttpResponse with attachment headers.

    Rows are consumed once — pass a list or a materialized queryset,
    not a lazy iterator you'll need again.
    """
    buf = StringIO()
    buf.write("﻿")  # BOM for Excel UTF-8 detection.
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([label for label, _ in columns])
    for row in rows:
        writer.writerow([_format(_resolve(row, getter)) for _, getter in columns])

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_stem}_{stamp}.csv"
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def wants_csv(request) -> bool:
    """Convenience predicate — return True when the request asked for CSV."""
    return request.GET.get("format") == "csv"
