"""Validate the repository plan registry without third-party dependencies."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
path = root / "docs" / "records" / "PLAN_REGISTRY.md"
allowed = {"active", "ready", "verify", "deferred", "completed", "superseded", "archived-only"}
text = path.read_text(encoding="utf-8")
parts = re.split(r"(?m)^## (PLAN-\d+) — .+$", text)
errors = []
seen = set()
for index in range(1, len(parts), 2):
    plan_id, body = parts[index], parts[index + 1]
    if plan_id in seen:
        errors.append(f"duplicate plan ID: {plan_id}")
    seen.add(plan_id)
    fields = dict(re.findall(r"(?m)^- ([A-Za-z ]+):\s*(.+)$", body))
    for required in ("Scope", "Status", "Defined", "Started", "Completed", "Blueprint", "Source", "Section", "Resume gate"):
        if not fields.get(required):
            errors.append(f"{plan_id} lacks {required}")
    status = fields.get("Status")
    if status not in allowed:
        errors.append(f"{plan_id} has invalid status: {status}")
    source = fields.get("Source", "").split("#", 1)[0]
    if source and not (root / source).is_file():
        errors.append(f"{plan_id} source does not exist: {source}")
    blueprint = fields.get("Blueprint", "—")
    if status == "active":
        if blueprint == "—" or not (root / blueprint).is_file():
            errors.append(f"{plan_id} is active but has no valid blueprint")
        elif plan_id not in (root / blueprint).read_text(encoding="utf-8"):
            errors.append(f"{plan_id} is not referenced by {blueprint}")
if not seen:
    errors.append("registry has no plan entries")
if errors:
    print("Plan registry validation failed:", *errors, sep="\n- ")
    sys.exit(1)
print(f"Plan registry validation passed ({len(seen)} entries).")
