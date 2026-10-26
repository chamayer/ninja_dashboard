"""PLAN-017 local source inventory. Never imports application code or opens a DB.

Run from any directory with write to create evidence, or check to compare
the saved baseline with current source. Outputs are lexical review leads, not
a SQL parser, migration-state simulator, call graph, or deployed catalog.
Only explicitly allowed source paths/extensions are read. No environment,
credential/configuration data files, .work, caches, or live services are read.
"""

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PREFIXES = ("ingest/", "shared/", "sql/", "operations/apps/",
            "operations/config/", "operations/templates/", "scripts/")
PACKAGING = {"docker-compose.yml", "docker-compose.workstation-ca.yml",
             "ingest/Dockerfile", "operations/Dockerfile",
             "operations/entrypoint.sh", "docker/postgres.Dockerfile"}
SOURCE_PLANS = ["operations/docs/plans/PLAN-017-data-architecture-review.md",
                "docs/plans/PLAN-018-end-to-end-data-ingest-review.md"]
SCHEMAS = ("operations", "ninja_core", "ninja_inventory", "ninja_patches",
           "ninja_activities", "ninja_agent_compliance", "intel", "catalog", "public")
OBJECT = r'"?(?:' + "|".join(SCHEMAS) + r')"?\s*\.\s*"?[A-Za-z_][\w]*"?'
OCCURRENCE = re.compile(
    r'\b(CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+VIEW|VIEW|TABLE|'
    r'FUNCTION|PROCEDURE|TRIGGER|(?:UNIQUE\s+)?INDEX)|ALTER\s+TABLE|'
    r'DROP\s+(?:MATERIALIZED\s+VIEW|VIEW|TABLE|FUNCTION|TRIGGER|INDEX)|'
    r'REFRESH\s+MATERIALIZED\s+VIEW|INSERT\s+INTO|UPDATE|DELETE\s+FROM|'
    r'FROM|JOIN|REFERENCES)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?'
    r'(?:CONCURRENTLY\s+)?(' + OBJECT + r')', re.I)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8")


def paths():
    names = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))
    return sorted(p for p in names if (ROOT / p).is_file() and
                  (p in PACKAGING or (p.startswith(PREFIXES) and
                   Path(p).suffix in {".py", ".sql", ".html", ".sh"})))


def destination(path):
    if "/tests/" in path or Path(path).name.startswith("test_"):
        return "R10-constraints-tests"
    if "/migrations/" in path or path.startswith("sql/"):
        return "R09-schema-constraints-catalog"
    if path in PACKAGING or path in {"ingest/main.py", "ingest/jobs_worker.py", "ingest/jobs_child.py"}:
        return "R01-entrypoints-jobs-publication"
    if path.startswith("ingest/identity/") or "client_evidence" in path or "client_domains" in path:
        return "R03-identity-scope-actions"
    if path.startswith(("ingest/intel/", "ingest/inventory/")) or "software" in path:
        return "R06-software-reference"
    if path.startswith(("ingest/activities/", "ingest/patches/", "ingest/core/", "ingest/agent_compliance/")):
        return "R07-native-legacy-domains"
    if path.startswith("ingest/connectors/") or Path(path).stem in {"observations", "observation_runs", "source_observations", "sources", "source_events"}:
        return "R02-acquisition-observations"
    if any(x in path for x in ("retention", "restore_", "backfill_")):
        return "R08-lifecycle-maintenance"
    if any(x in path for x in ("evaluator", "requirement", "finding", "condition", "notification", "policy_scope")):
        return "R05-policy-findings-notifications"
    if path.startswith(("operations/", "scripts/")):
        return "R11-readers-admin-exports"
    return "R04-projection-shared-contracts"


def write_csv(name, fields, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["write", "check"])
    args = parser.parse_args()
    if args.mode == "check":
        saved = json.loads((OUT / "source-baseline.json").read_text(encoding="utf-8"))
        changed = [row["path"] for row in saved["files"]
                   if not (ROOT / row["path"]).is_file() or digest(row["path"]) != row["sha256"]]
        added = sorted(set(paths()) - {row["path"] for row in saved["files"]})
        head_changed = git("rev-parse", "HEAD").strip() != saved["head"]
        print(json.dumps({"head_changed": head_changed, "changed_or_missing": changed,
                          "added_source": added}, indent=2))
        return int(bool(changed or added or head_changed))
    if (OUT / "source-baseline.json").exists():
        raise SystemExit("Baseline already exists; preserve it and create a separately named next baseline.")
    status = {}
    for line in git("status", "--porcelain=v1", "-uall").splitlines():
        status[line[3:]] = line[:2]
    files, occurrences, entries = [], [], []
    for path in paths() + SOURCE_PLANS:
        data = (ROOT / path).read_bytes()
        source = data.decode("utf-8-sig")
        route = destination(path) if path not in SOURCE_PLANS else "provenance-only"
        files.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                      "bytes": len(data), "lines": len(source.splitlines()),
                      "git_status": status.get(path, "tracked-clean"), "review_destination": route})
        if path in SOURCE_PLANS:
            continue
        for match in OCCURRENCE.finditer(source):
            occurrences.append({"path": path, "line": source.count("\n", 0, match.start()) + 1,
                                "operation": " ".join(match[1].upper().split()),
                                "object": re.sub(r'["\s]', '', match[2]).lower(),
                                "review_destination": route})
        if path.endswith(".py"):
            tree = ast.parse(source, filename=path)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    entries.append({"path": path, "line": node.lineno, "kind": type(node).__name__,
                                    "name": node.name, "review_destination": route})
    baseline = {"review_date": "2026-10-25", "head": git("rev-parse", "HEAD").strip(),
                "branch": git("branch", "--show-current").strip(),
                "scope": "Local working tree; no deployed version or live catalog established",
                "adopted_input_sha256": "3f1e29317e977a9486c98f0c1f75a5f1328c813699b9b7c508c8c60a730ac95e",
                "files": files}
    (OUT / "source-baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    write_csv("file-routing.csv", ["path", "lines", "git_status", "review_destination"],
              [{key: row[key] for key in ("path", "lines", "git_status", "review_destination")} for row in files])
    write_csv("object-occurrences.csv", ["path", "line", "operation", "object", "review_destination"], occurrences)
    write_csv("python-definitions.csv", ["path", "line", "kind", "name", "review_destination"], entries)
    print(json.dumps({"baseline_files": len(files), "lexical_occurrences": len(occurrences),
                      "distinct_object_names": len({row['object'] for row in occurrences}),
                      "top_level_python_definitions": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
