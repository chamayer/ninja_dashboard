"""PLAN-017 Phase 3 transport, adapted from the Phase 1 runner.

Reads the wrapper and M-bodies verbatim from PLAN-017-phase-3-query-draft.md
and P0 from PLAN-017-diagnostic-queries.md. Each body runs on a fresh psql
connection as operations_migrate inside the read-only, rolled-back wrapper,
after P0 passes. Plans keep only structural fields. Evidence files are never
overwritten. Usage (repository root):

    python docs/records/PLAN-017-phase-3/run_phase3.py <label> [--plan] M0 M0b ...
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

ROOT = pathlib.Path(__file__).resolve().parents[3]
DRAFT = ROOT / "docs/records/PLAN-017-phase-3-query-draft.md"
PHASE1 = ROOT / "docs/records/PLAN-017-diagnostic-queries.md"
EVIDENCE = pathlib.Path(__file__).resolve().parent
BUDGET_SECONDS = 25

draft_text = DRAFT.read_text(encoding="utf-8")
blocks = re.findall(r"```sql\n(.*?)```", draft_text, re.S)
PREFIX, SUFFIX = blocks[0].split("-- One numbered body.")
P0 = next(
    b for b in re.findall(r"```sql\n(.*?)```", PHASE1.read_text(encoding="utf-8"), re.S)
    if b.startswith("-- P0:")
)
BODIES = {}
for statements in blocks[1:]:  # the statement block, then any revision blocks
    heads = list(re.finditer(r"^-- (M\d+[a-z]?)\b[^\n]*\n", statements, re.M))
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(statements)
        assert head.group(1) not in BODIES, head.group(1)
        BODIES[head.group(1)] = statements[head.end():end].strip()

REMOTE = r'''
import subprocess,json,time,csv,io,os,selectors,datetime,re
payload = PAYLOAD
started=time.monotonic(); deadline=started+max(0,payload['budget_seconds']-3)
results=[]; stopped=None
def read_preflight(proc):
    output=b''; selector=selectors.DefaultSelector(); selector.register(proc.stdout,selectors.EVENT_READ)
    try:
        while b'PLAN017_P0_END\n' not in output:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('batch_deadline')
            if not selector.select(min(remaining,6)): raise TimeoutError('preflight_deadline')
            chunk=os.read(proc.stdout.fileno(),4096)
            if not chunk: raise ValueError('preflight_incomplete')
            output+=chunk
            if len(output)>10000: raise ValueError('preflight_output_limit')
        rows=list(csv.DictReader(io.StringIO(output.split(b'PLAN017_P0_END\n')[0].decode())))
        if len(rows)!=1: raise ValueError('preflight_shape')
        row=rows[0]
        valid=(row.get('executing_role')=='operations_migrate' and row.get('transaction_read_only')=='on'
          and row.get('tenant_context')=='1' and row.get('executing_search_path')=='pg_catalog'
          and 160000<=int(row.get('server_version_num','0'))<170000 and row.get('rolbypassrls')=='t')
        if not valid: raise ValueError('preflight_mismatch')
        return row
    finally: selector.close()
def safe_plan(node):
    allowed={'Node Type','Parent Relationship','Join Type','Strategy','Partial Mode','Parallel Aware',
      'Async Capable','Startup Cost','Total Cost','Plan Rows','Plan Width','Relation Name','Schema','Alias',
      'Index Name','Scan Direction','Workers Planned','Subplan Name','CTE Name'}
    result={key:value for key,value in node.items() if key in allowed}
    if 'Plans' in node: result['Plans']=[safe_plan(x) for x in node['Plans']]
    return result
for item in payload['items']:
    if time.monotonic()>=deadline: stopped='batch_deadline';break
    proc=None; entry={'query':item['id'],'mode':item['mode']}; results.append(entry); query_started=time.monotonic()
    try:
        proc=subprocess.Popen(['docker','exec','-i','ninja-postgres','psql','-X','-w','-U','operations_migrate',
          '-d','ninja','-q','--csv','-v','ON_ERROR_STOP=1','-v','VERBOSITY=sqlstate'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        proc.stdin.write((payload['prefix']+payload['p0']+'\n\\echo PLAN017_P0_END\n').encode());proc.stdin.flush()
        entry['preflight']=read_preflight(proc)
        remaining=deadline-time.monotonic()
        if remaining<=0: raise TimeoutError('batch_deadline')
        output,error=proc.communicate((item['sql']+'\n'+payload['suffix']+'\n\\q\n').encode(),timeout=remaining)
        entry['exit_code']=proc.returncode
        if proc.returncode:
            code=re.search(rb'ERROR:\s+([A-Z0-9]{5})\b',error)
            entry['status']='query_error';entry['sqlstate']=code.group(1).decode() if code else None
            stopped='query_error';break
        rows=list(csv.DictReader(io.StringIO(output.decode())))
        entry['returned_rows']=len(rows)
        if item['mode']=='plain_explain':
            if len(rows)!=1 or set(rows[0])!={'QUERY PLAN'}: raise ValueError('plan_output_shape')
            plan=json.loads(rows[0]['QUERY PLAN'])[0]
            if any('Actual' in k or 'Execution Time' in k for k in plan): raise ValueError('unexpected_executed_plan')
            entry['plan']=safe_plan(plan['Plan'])
        else:
            entry['rows']=rows
        entry['status']='ok'
    except subprocess.TimeoutExpired:
        entry['status']='deadline';stopped='deadline';break
    except (ValueError,TimeoutError) as exc:
        entry['status']='validation_or_deadline_stop';entry['category']=str(exc);stopped=str(exc);break
    except Exception:
        entry['status']='transport_error';stopped='transport_error';break
    finally:
        if proc and proc.poll() is None:
            proc.kill()
            try:proc.communicate(timeout=2)
            except Exception:pass
        entry['wall_seconds']=round(time.monotonic()-query_started,3)
print(json.dumps({'captured_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'wall_seconds':round(time.monotonic()-started,3),'stop_reason':stopped,'results':results}))
'''


def helper(target: str, timeout: int):
    command = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "-NoProfile",
        "-ExecutionPolicy", "Bypass", "-File",
        str((ROOT / "../Scripts/Invoke-DevTool.ps1").resolve()), "am-ch-01", "ssh", target,
    ]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def capture(label: str, ids: list[str], explain: bool, timeout: str | None = None):
    prefix = PREFIX
    if timeout is not None:
        # Revision 2: only M2r may run with the 15-second limit.
        assert timeout == "15s" and ids == ["M2r"] and not explain
        assert prefix.count("SET LOCAL statement_timeout = '5s';") == 1
        prefix = prefix.replace("statement_timeout = '5s'", "statement_timeout = '15s'")
    items = []
    for ident in ids:
        sql = BODIES[ident]
        if explain:
            assert ident in {"M1", "M2", "M3", "M4", "M5", "M1r", "M2r", "M3r"}
            sql = "EXPLAIN (ANALYZE FALSE, FORMAT JSON)\n" + sql
        items.append({"id": ident, "sql": sql,
                      "mode": "plain_explain" if explain else "metadata_or_aggregate"})
    payload = {"prefix": prefix, "suffix": SUFFIX, "p0": P0, "items": items,
               "budget_seconds": BUDGET_SECONDS}
    script = REMOTE.replace("PAYLOAD", repr(payload), 1)
    target = "printf %s " + base64.b64encode(script.encode()).decode() + " | base64 -d | python3"
    destination = EVIDENCE / f"{label}.json"
    if destination.exists():
        raise RuntimeError("Refusing evidence overwrite")
    start = time.monotonic()
    try:
        proc = helper(target, BUDGET_SECONDS + 5)
        if proc.returncode:
            result = {"stop_reason": "helper_error", "helper_exit_code": proc.returncode}
        else:
            result = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        result = {"stop_reason": "client_deadline"}
    except (ValueError, UnicodeError):
        result = {"stop_reason": "output_validation"}
    result["label"] = label
    result["statement_timeout"] = timeout or "5s"
    result["client_wall_seconds"] = round(time.monotonic() - start, 3)
    result["draft_sha256"] = hashlib.sha256(DRAFT.read_bytes()).hexdigest()
    result["submitted_sql_sha256"] = {
        i["id"]: hashlib.sha256(i["sql"].encode()).hexdigest() for i in items}
    with destination.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, indent=2)
        out.write("\n")
    print(json.dumps({"evidence": str(destination.relative_to(ROOT)), **{
        k: result.get(k) for k in ("stop_reason", "helper_exit_code", "client_wall_seconds")}},
        indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]
    label = args.pop(0)
    explain = "--plan" in args
    timeout = None
    if "--timeout" in args:
        i = args.index("--timeout")
        timeout = args[i + 1]
        del args[i:i + 2]
    ids = [a for a in args if a != "--plan"]
    assert ids and all(i in BODIES for i in ids), (ids, sorted(BODIES))
    capture(label, ids, explain, timeout)
