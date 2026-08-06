# Legacy software decision corpus

`legacy-software-decisions-2026-07-03.csv` — 418 operator decisions accumulated
by `inventory-scripts/SW Inventory/analyze_inventory.py` over its operating
life, exported 2026-07-03. 303 title-scope, 115 publisher-scope.

Filed here because it is the **provenance record** for the rows this platform
now holds in `operations.software_decisions`. It is not expected to be used
again after the one-time import: from that point the database is the live
record, and new decisions are made in the Operations UI.

It is committed rather than left in `inventory-scripts/` because that folder is
gitignored — deliberately, since it also contains a collector script with live
Ninja API credentials. This file has none: three columns, software and
publisher names only, no client identifiers.

## Importing it

```bash
python manage.py import_software_decisions \
    --file docs/reference/legacy-software-decisions-2026-07-03.csv
```

Dry run by default; add `--apply` to write. Idempotent, and it never overwrites
a decision an operator has since changed in the UI — it only touches rows
carrying its own import `reason`.

## Mapping

| CSV | `SoftwareDecision` |
| --- | --- |
| `Approve` + `software` | `approve`, `canonical_name` set |
| `Reject` + `software` | `reject`, `canonical_name` set |
| `Investigate` + `software` | `investigate`, `canonical_name` set |
| `Approve` + `publisher` | `approve_publisher`, `publisher` set |
| `Approve Publisher` + `publisher` | `approve_publisher`, `publisher` set |
| `Reject` / `Investigate` + `publisher` | same value, `publisher` set |

The corpus carries two spellings for publisher approval because the legacy VBA
wrote the publisher name with `Type=publisher` whichever button was pressed.
Both mean the same thing.

All rows import at **global scope** (`client_id` and `device_id` NULL), which
matches the legacy semantics — `decisions_{client}.csv` was always written
identical to `decisions_global.csv`.

## Why it matters

Measured 2026-08-06 before import: this corpus decides **814 of the 1,867**
open `whitelist_suggestion` (title, publisher) pairs — 44% — with the 115
publisher-scope decisions carrying 740 of them against 215 from the 303
title-scope ones. A publisher sits above a product in the ADR-0012 §5
hierarchy, which is why so few of them do so much.

See ADR-0015 for how decisions relate to classification, categorisation and
findings.
