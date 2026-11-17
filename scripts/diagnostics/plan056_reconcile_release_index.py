"""Advance only the released view function in the preserved original index."""
import ast
from pathlib import Path
import subprocess
import tempfile


def read(ref):
    return subprocess.run(["git", "show", ref], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def bounds(source):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "source_records")
    return min([node.lineno] + [d.lineno for d in node.decorator_list])-1, node.end_lineno


path = "operations/apps/core/views.py"
staged, released = read(":"+path), read("HEAD:"+path)
start, end = bounds(staged)
new_start, new_end = bounds(released)
content = "".join(staged.splitlines(keepends=True)[:start]
                  + released.splitlines(keepends=True)[new_start:new_end]
                  + staged.splitlines(keepends=True)[end:])
ast.parse(content)
with tempfile.TemporaryDirectory(prefix="ninja-index-reconcile-") as directory:
    candidate = Path(directory)/"views.py"
    candidate.write_text(content, encoding="utf-8")
    blob = subprocess.run(["git", "hash-object", "-w", "--path="+path, str(candidate)],
                          check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644", blob, path], check=True)
subprocess.run(["git", "restore", "--staged", "--source=HEAD", "--", "VERSION",
                "CHANGELOG.md", "operations/apps/core/issue_selection.py",
                "operations/apps/core/source_record_views.py"], check=True)
print("Original unrelated staging preserved; released files advanced to HEAD.")
