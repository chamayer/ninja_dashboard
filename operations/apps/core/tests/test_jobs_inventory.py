"""Source-only discovery evidence; never imports workers or connects to a DB.

This snapshot is NOT the executable registry. Static syntax coverage cannot
certify retry safety or prove the behavior of dynamic dispatch.
"""

import ast
import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
INVENTORY_PATH = ROOT / "shared" / "jobs_inventory.json"
RELATION = re.compile(r"\b(?:operations|ninja_core)\.[a-z_][a-z_0-9]*\b")
EXCLUDED = {"tests", "migrations", "__pycache__"}


def _runtime_sources():
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for base in (ROOT / "ingest", ROOT / "operations" / "apps", ROOT / "shared")
        for path in sorted(base.rglob("*.py"))
        if not EXCLUDED.intersection(path.relative_to(ROOT).parts)
    }


def _expr(node):
    return ast.unparse(node) if node is not None else None


def _queue_relation(name):
    short = name.split(".")[-1]
    return "queue" in short or short.endswith(("job_runs", "action_requests"))


class Discovery(ast.NodeVisitor):
    def __init__(self, path, records):
        self.path = path
        self.records = records
        self.context = []
        self.guards = []
        self.bindings = [{}]

    def record(self, bucket, **fields):
        self.records[bucket].append({"file": self.path, "owner": ".".join(self.context), **fields})

    def visit_ClassDef(self, node):
        self.context.append(node.name)
        self.generic_visit(node)
        self.context.pop()

    def visit_FunctionDef(self, node):
        self.context.append(node.name)
        # Retain expressions, not values: assignments can be conditional.
        self.bindings.append({})
        self.generic_visit(node)
        self.bindings.pop()
        self.context.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node):
        self.visit(node.test)
        branches = (
            (node.body, _expr(node.test)),
            (node.orelse, f"not ({_expr(node.test)})"),
        )
        for branch, label in branches:
            self.guards.append(label)
            for child in branch:
                self.visit(child)
            self.guards.pop()

    def visit_For(self, node):
        self.guards.append(f"for {_expr(node.target)} in {_expr(node.iter)}")
        self.generic_visit(node)
        self.guards.pop()

    def visit_Assign(self, node):
        for target in node.targets:
            self.assignment(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.assignment(node.target, node.value)
        self.generic_visit(node)

    def assignment(self, target, value):
        if not isinstance(target, ast.Name) or value is None:
            return
        self.bindings[-1][target.id] = _expr(value)
        if target.id == "_JOB_CATALOG" and isinstance(value, ast.List | ast.Tuple):
            for entry in ast.literal_eval(value):
                self.record("catalog", **entry)
        if self.path.endswith("operator_job_queue.py") and target.id == "jobs":
            if not isinstance(value, ast.Dict):
                raise AssertionError("Dispatcher shape changed: update discovery")
            for key, definition in zip(value.keys, value.values, strict=True):
                self.record("handlers", key=ast.literal_eval(key), expression=_expr(definition))

    def visit_Return(self, node):
        if (
            self.path.endswith("operator_job_queue.py")
            and self.context == ["_execute"]
            and isinstance(node.value, ast.Call)
            and _expr(node.value.func) == "_software_classify_with_intel"
        ):
            self.record("handlers", key="software-classify", expression=_expr(node.value))
        self.generic_visit(node)

    def visit_Compare(self, node):
        self.route_literals(node, "comparison")
        self.generic_visit(node)

    def route_literals(self, node, match):
        if not any(name in {"do_GET", "do_POST"} for name in self.context):
            return
        for item in ast.walk(node):
            if (
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value.startswith("/")
            ):
                self.record("http_routes", route=item.value, match=match)

    def visit_Call(self, node):
        name = _expr(node.func)
        short = name.rsplit(".", 1)[-1]
        keywords = {kw.arg: kw.value for kw in node.keywords}
        if short == "add_job":
            self.record(
                "schedules",
                id=_expr(keywords.get("id")),
                callable=_expr(node.args[0]) if node.args else None,
                trigger=(
                    _expr(node.args[1]) if len(node.args) > 1 else _expr(keywords.get("trigger"))
                ),
                options={str(k): _expr(v) for k, v in keywords.items() if k != "id"},
                guards=list(self.guards),
            )
        if short == "Thread":
            self.record("threads", expression=_expr(node), guards=list(self.guards))
        if short == "run_log":
            argument = node.args[0] if node.args else keywords.get("kind")
            binding = None
            if isinstance(argument, ast.Name):
                binding = next(
                    (
                        scope[argument.id]
                        for scope in reversed(self.bindings)
                        if argument.id in scope
                    ),
                    None,
                )
            self.record("run_logs", argument=_expr(argument), local_binding=binding)
        if short in {"startswith", "endswith"}:
            self.route_literals(node, short)
        if (
            self.path == "ingest/main.py"
            and self.context == ["main"]
            and short
            not in {
                "add_job",
                "validate_registry",
                "info",
                "warning",
                "exception",
                "error",
                "debug",
            }
        ):
            self.record("startup_calls", expression=_expr(node), guards=list(self.guards))
        if short in {
            "enqueue",
            "enqueue_and_run",
            "enqueue_automatic",
            "refresh_after_collection",
            "schedule_agent_compliance_evaluate",
        }:
            self.record("admission_and_followup_calls", expression=_expr(node))
        self.generic_visit(node)


def discover(sources):
    records = {
        key: []
        for key in (
            "schedules",
            "http_routes",
            "threads",
            "run_logs",
            "catalog",
            "handlers",
            "startup_calls",
            "admission_and_followup_calls",
            "queues",
            "consumers",
            "raw_run_log_writers",
        )
    }
    queue_files = {}
    for path, source in sorted(sources.items()):
        tree = ast.parse(source, filename=path)
        Discovery(path, records).visit(tree)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        strings = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        relations = sorted({match for value in strings for match in RELATION.findall(value)})
        for relation in relations:
            if _queue_relation(relation):
                queue_files.setdefault(relation, []).append(path)
        relevant = [
            name
            for name in relations
            if _queue_relation(name) or name.endswith(".run_log") or "job_events" in name
        ]
        if relevant:
            records["consumers"].append({"file": path, "relations": relevant})
        for value in strings:
            if re.search(r"INSERT\s+INTO\s+operations\.run_log\b", value, re.I):
                records["raw_run_log_writers"].append(
                    {"file": path, "sql": " ".join(value.split())}
                )
    records["queues"] = [
        {"relation": name, "files": paths} for name, paths in sorted(queue_files.items())
    ]
    if "shared/jobs_registry.py" in sources:
        from shared.jobs_registry import catalog_entries

        records["catalog"] = [
            {"file": "operations/apps/core/views.py", "owner": "", **entry}
            for entry in catalog_entries()
        ]
    return records


def _assert_inventory_complete(inventory, expected):
    assert inventory["evidence"] == expected
    catalog = [entry["id"] for entry in expected["catalog"]]
    handlers = [entry["key"] for entry in expected["handlers"]]
    assert len(catalog) == len(set(catalog))
    assert len(handlers) == len(set(handlers))
    assert set(catalog) == set(handlers)


@pytest.fixture(scope="module")
def evidence():
    return discover(_runtime_sources())


def test_jobs_inventory_is_machine_checked(evidence):
    _assert_inventory_complete(json.loads(INVENTORY_PATH.read_text(encoding="utf-8")), evidence)


def test_each_inventory_category_rejects_omission(evidence):
    for category, entries in evidence.items():
        assert entries, category
        omitted = copy.deepcopy(evidence)
        omitted[category].pop()
        with pytest.raises(AssertionError):
            _assert_inventory_complete({"evidence": omitted}, evidence)


def test_discovery_detects_independent_new_paths():
    source = """
def main():
    for region in regions:
        scheduler.add_job(work, "interval", id=f"new_{region}", minutes=7)
    enqueue_automatic("new-work")
class Handler:
    def do_GET(self):
        if self.path in ("/run/sources", "/run/new"):
            Thread(target=work).start()
def work():
    kind = "inventory.software.scoped" if scope else "inventory.software"
    with run_log(kind):
        execute("UPDATE operations.unseen_queue SET status = 'done'")
"""
    result = discover({"ingest/main.py": source})
    assert result["schedules"][0]["id"] == "f'new_{region}'"
    assert result["schedules"][0]["guards"] == ["for region in regions"]
    assert {row["route"] for row in result["http_routes"]} == {"/run/sources", "/run/new"}
    assert result["threads"][0]["owner"] == "Handler.do_GET"
    assert result["run_logs"][0]["local_binding"] == (
        "'inventory.software.scoped' if scope else 'inventory.software'"
    )
    assert result["queues"][0]["relation"] == "operations.unseen_queue"
    assert result["startup_calls"] and result["admission_and_followup_calls"]
    with pytest.raises(AssertionError):
        _assert_inventory_complete({"evidence": discover({})}, result)


def test_comments_and_docstrings_are_not_executors():
    result = discover(
        {
            "ingest/example.py": '''
# scheduler.add_job(fake)
"""operations.imaginary_queue run_log('fake')"""
def example():
    """operations.another_queue"""
    pass
'''
        }
    )
    assert not any(result.values())
