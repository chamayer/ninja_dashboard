"""Summarize Ninja custom fields — distinct names, value preview, size.

Walks /queries/custom-fields, aggregates by field name, prints a table
showing how big the values typically get. Useful to pick a sane
INGEST_CUSTOM_FIELDS_INCLUDE allowlist.

Usage:
    docker exec -it ninja-ingest python -m ingest.probe_fields

Options:
    --records N    scan up to N records (default 1000)
    --page-size N  request size per page (default 100)
    --preview N    chars of value preview (default 10)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from ingest.config import settings
from ingest.ninja_client import NinjaClient


def _value_text(v: Any) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), default=str)
    return str(v)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Ninja custom fields")
    parser.add_argument("--records", type=int, default=1000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--preview", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level="WARNING", format="%(levelname)s %(name)s %(message)s")

    # name -> [preview_chars, max_size, occurrences]
    fields: dict[str, list[Any]] = {}
    records_seen = 0

    with NinjaClient(
        base_url=settings.NINJA_BASE_URL,
        token_url=settings.NINJA_TOKEN_URL,
        client_id=settings.NINJA_CLIENT_ID,
        client_secret=settings.NINJA_CLIENT_SECRET.get_secret_value(),
        scope=settings.NINJA_SCOPE,
    ) as client:
        for rec in client.paginate_cursor(
            "/queries/custom-fields", page_size=args.page_size,
        ):
            records_seen += 1
            for fname, fval in (rec.get("fields") or {}).items():
                text = _value_text(fval)
                size = len(text)
                if fname not in fields:
                    fields[fname] = [
                        text[:args.preview].replace("\n", " ").replace("\r", " "),
                        size,
                        1,
                    ]
                else:
                    fields[fname][2] += 1
                    if size > fields[fname][1]:
                        fields[fname][0] = (
                            text[:args.preview]
                            .replace("\n", " ")
                            .replace("\r", " ")
                        )
                        fields[fname][1] = size
            if records_seen >= args.records:
                break

    if not fields:
        print("No custom fields found.")
        return 0

    print(f"\nScanned {records_seen} device records, found {len(fields)} distinct fields:\n")
    name_w = max(20, max(len(n) for n in fields))
    prev_w = max(args.preview, 7)
    print(
        f"{'Field name'.ljust(name_w)}  "
        f"{'Preview'.ljust(prev_w)}  "
        f"{'MaxSize':>7}  "
        f"{'Count':>6}"
    )
    print(f"{'-' * name_w}  {'-' * prev_w}  {'-' * 7}  {'-' * 6}")
    for name in sorted(fields):
        preview, size, count = fields[name]
        print(
            f"{name.ljust(name_w)}  "
            f"{preview.ljust(prev_w)}  "
            f"{size:>7}  "
            f"{count:>6}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
