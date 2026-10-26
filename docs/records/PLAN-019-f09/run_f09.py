"""PLAN-019 F09 read-only estimate, reusing the PLAN-017 Phase 3 transport.

Same wrapper (read-only, rolled back, 5 s statement timeout), P0 preflight
and per-query fresh psql connection as Phase 3; aggregate rows only.
Evidence files are never overwritten. Usage (repository root):

    python docs/records/PLAN-019-f09/run_f09.py <label> [--plan] F1 F2 ...
"""

import base64
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "PLAN-017-phase-3"))
import run_phase3 as p3  # noqa: E402

QUERIES = HERE / "queries.sql"
text = QUERIES.read_text(encoding="utf-8")
BODIES = {}
heads = list(re.finditer(r"^-- (F\d+):[^\n]*\n", text, re.M))
for i, head in enumerate(heads):
    end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
    BODIES[head.group(1)] = text[head.end():end].strip()


def capture(label, ids, explain):
    items = []
    for ident in ids:
        sql = BODIES[ident]
        if explain:
            sql = "EXPLAIN (ANALYZE FALSE, FORMAT JSON)\n" + sql
        items.append({"id": ident, "sql": sql,
                      "mode": "plain_explain" if explain else "metadata_or_aggregate"})
    payload = {"prefix": p3.PREFIX, "suffix": p3.SUFFIX, "p0": p3.P0, "items": items,
               "budget_seconds": p3.BUDGET_SECONDS}
    script = p3.REMOTE.replace("PAYLOAD", repr(payload), 1)
    target = "printf %s " + base64.b64encode(script.encode()).decode() + " | base64 -d | python3"
    destination = HERE / f"{label}.json"
    if destination.exists():
        raise RuntimeError("Refusing evidence overwrite")
    start = time.monotonic()
    try:
        proc = p3.helper(target, p3.BUDGET_SECONDS + 5)
        result = ({"stop_reason": "helper_error", "helper_exit_code": proc.returncode}
                  if proc.returncode else json.loads(proc.stdout))
    except subprocess.TimeoutExpired:
        result = {"stop_reason": "client_deadline"}
    except (ValueError, UnicodeError):
        result = {"stop_reason": "output_validation"}
    result["label"] = label
    result["client_wall_seconds"] = round(time.monotonic() - start, 3)
    result["queries_sha256"] = hashlib.sha256(QUERIES.read_bytes()).hexdigest()
    result["captured_by_client_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with destination.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, indent=2)
        out.write("\n")
    print(json.dumps({k: result.get(k) for k in ("label", "stop_reason", "client_wall_seconds")}))


if __name__ == "__main__":
    args = sys.argv[1:]
    label = args.pop(0)
    explain = "--plan" in args
    ids = [a for a in args if a != "--plan"]
    assert ids and all(i in BODIES for i in ids), (ids, sorted(BODIES))
    capture(label, ids, explain)
