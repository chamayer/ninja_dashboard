"""Package only the reviewed Source Records function and its shared readers."""
import ast
from pathlib import Path
import subprocess
import sys

destination = Path(sys.argv[1])
destination.mkdir()
baseline = subprocess.run(["git", "show", "HEAD:operations/apps/core/views.py"], check=True, capture_output=True, text=True, encoding="utf-8").stdout
working = Path("operations/apps/core/views.py").read_text(encoding="utf-8")

def bounds(source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "source_records")
    return min([node.lineno]+[n.lineno for n in node.decorator_list])-1, node.end_lineno

start, end = bounds(baseline)
new_start, new_end = bounds(working)
base_lines, new_lines = baseline.splitlines(keepends=True), working.splitlines(keepends=True)
candidate = "".join(base_lines[:start]+new_lines[new_start:new_end]+base_lines[end:])
ast.parse(candidate)
(destination/"plan056_records_views_candidate.py").write_text(candidate, encoding="utf-8")
for source, target in (
    ("operations/apps/core/source_record_views.py", "plan056_records_domain_candidate.py"),
    ("operations/apps/core/issue_selection.py", "plan056_records_issues_candidate.py"),
    ("operations/apps/core/context_processors.py", "plan056_records_context_candidate.py"),
):
    content = Path(source).read_text(encoding="utf-8")
    ast.parse(content)
    (destination/target).write_text(content, encoding="utf-8")
print("Three source candidates prepared; only Source Records replaces the baseline view function.")
