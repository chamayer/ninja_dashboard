"""Authorized Coverage cancellation and one instrumented retry; no runtime edits.

Host mode uses the documented inspection connection for catalogs/cancellation.
HTTP mode runs inside Operations with the existing normal-login helper.
Only redacted metadata is emitted. Never print SQL, bodies, secrets or errors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone


PAGE_LIMIT = 120
OLD = {
    "pid": 363232,
    "backend_start": "2026-11-10T19:40:10.695865+00:00",
    "xact_start": "2026-11-10T19:40:10.722880+00:00",
    "query_start": "2026-11-10T19:40:11.907387+00:00",
}
SNAPSHOT = """
SELECT jsonb_build_object(
 'utc',clock_timestamp(),
 'visible',pg_has_role(current_user,'pg_read_all_stats','MEMBER'),
 'database',(SELECT to_jsonb(d) FROM (
   SELECT blks_read,blks_hit,temp_files,temp_bytes,tup_inserted,tup_updated,
          tup_deleted,deadlocks,stats_reset FROM pg_stat_database
   WHERE datname=current_database()) d),
 'sessions',(SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]') FROM (
   SELECT pid,leader_pid,backend_start,xact_start,query_start,state,
          wait_event_type,wait_event,cardinality(pg_blocking_pids(pid)) AS blockers,
          md5(query) AS query_hash,
          query ILIKE '%operations.v_hudu_computer_inventory_observation_current%'
            AS hudu,
          query ILIKE '%operations.device_requirement_state%' AS requirements
   FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
     AND (state='active' OR state LIKE 'idle in transaction%')
   ORDER BY query_start NULLS LAST,pid LIMIT 100) a))
"""


def emit(section, **values):
    print(
        json.dumps(
            {
                "utc": datetime.now(timezone.utc).isoformat(),
                "section": section,
                **values,
            }
        ),
        flush=True,
    )


def sql(statement):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=3000 "
            "-c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000",
            "ninja-postgres",
            "psql",
            "-X",
            "-q",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "ninja",
            "-d",
            "ninja",
        ],
        input="BEGIN READ ONLY;\n" + statement + ";\nROLLBACK;\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("inspection_failed")
    return json.loads(result.stdout.strip())


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def cancel(target, label):
    # Pin the exact backend, transaction AND statement observed most recently.
    # A reused PID, new transaction or different statement fails closed.
    predicate = " AND ".join(
        [f"pid={int(target['pid'])}", "state='active'"]
        + [
            f"{field}={literal(target[field])}::timestamptz"
            for field in ("backend_start", "xact_start", "query_start")
        ]
        + [f"md5(query)={literal(target['query_hash'])}"]
        + ["query ILIKE '%operations.v_hudu_computer_inventory_observation_current%'"]
    )
    result = sql(
        "WITH target AS MATERIALIZED (SELECT pid FROM pg_stat_activity WHERE "
        + predicate
        + ") SELECT jsonb_build_object('matched',(SELECT count(*) FROM target),"
        "'cancel_sent',COALESCE((SELECT pg_cancel_backend(pid) FROM target),false))"
    )
    emit("cancel", label=label, pid=target["pid"], **result)
    return result


def same_time(left, right):
    return bool(left and right) and datetime.fromisoformat(
        left
    ) == datetime.fromisoformat(right)


def transaction_active(snapshot, target):
    return any(
        row["pid"] == target["pid"]
        and same_time(row["backend_start"], target["backend_start"])
        and same_time(row["xact_start"], target["xact_start"])
        for row in snapshot["sessions"]
    )


def process_counters(pid):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "ninja-postgres",
            "cat",
            f"/proc/{int(pid)}/stat",
            f"/proc/{int(pid)}/io",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode:
        return {"available": False}
    lines = result.stdout.splitlines()
    fields = lines[0].rsplit(")", 1)[1].split()
    counters = {
        "cpu_ticks": int(fields[11]) + int(fields[12]),
        "process_start_ticks": int(fields[19]),
    }
    for line in lines[1:]:
        key, value = line.split(":", 1)
        if key in ("read_bytes", "write_bytes", "rchar", "wchar"):
            counters[key] = int(value)
    return counters


def host_counters():
    cpu = Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    return {
        "cpu_ticks": [int(value) for value in cpu],
        "available_kib": int(memory["MemAvailable"].split()[0]),
    }


def http():
    from plan056_http_pilot import main

    def measure(request, prefix):
        marker = prefix + "_1"
        started = time.monotonic()
        emit(
            "page_start",
            marker=marker,
            route="/inventory/computers/",
            epoch=time.time(),
            measurement_limit_s=PAGE_LIMIT,
            client_deadline_s=150,
        )

        def deadline(signum, frame):
            raise TimeoutError()

        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, 150)
        try:
            with request(
                "/inventory/computers/?_plan056=" + marker, timeout=150
            ) as response:
                headers_s = time.monotonic() - started
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                emit(
                    "page",
                    marker=marker,
                    status=response.status,
                    headers_s=round(headers_s, 3),
                    elapsed_s=round(time.monotonic() - started, 3),
                    bytes=size,
                )
                return 0 if response.status == 200 else 1
        except Exception as error:
            emit(
                "page_incomplete",
                marker=marker,
                error=type(error).__name__,
                elapsed_s=round(time.monotonic() - started, 3),
            )
            return 1
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    return main(measure)


def host():
    initial = sql(SNAPSHOT)
    emit("initial", snapshot=initial)
    if not initial["visible"] or len(initial["sessions"]) >= 100:
        raise RuntimeError("incomplete_visibility")
    old = next((row for row in initial["sessions"] if row["pid"] == OLD["pid"]), None)
    if old is not None:
        if not old["hudu"] or not all(
            same_time(old[field], OLD[field])
            for field in ("backend_start", "xact_start", "query_start")
        ):
            raise RuntimeError("original_identity_changed_no_cancel_or_retry")
        cancel(old, "original")
        time.sleep(1)
    baseline = sql(SNAPSHOT)
    old_closed = not transaction_active(baseline, OLD)
    emit("original_verified", transaction_closed=old_closed, snapshot=baseline)
    if not old_closed or any(
        row["hudu"] or row["requirements"] for row in baseline["sessions"]
    ):
        raise RuntimeError("coverage_work_survives_no_retry")

    events = queue.Queue()
    client = subprocess.Popen(
        [
            "docker",
            "exec",
            "ninja-operations",
            "python",
            "/tmp/plan056_coverage_retry.py",
            "http",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    def pump():
        for line in client.stdout:
            events.put(json.loads(line))
        events.put(None)

    threading.Thread(target=pump, daemon=True).start()
    epoch = None
    target = None
    next_sample = 0
    cancel_attempted = False
    started = time.monotonic()
    latest = baseline
    try:
        while time.monotonic() - started < 240:
            try:
                event = events.get(timeout=0.25)
                if event is None:
                    break
                if event["section"] == "page_start":
                    epoch = event["epoch"]
                print(json.dumps(event), flush=True)
            except queue.Empty:
                pass
            if epoch is None or time.monotonic() < next_sample:
                continue
            latest = sql(SNAPSHOT)
            candidates = [
                row
                for row in latest["sessions"]
                if (row["hudu"] or row["requirements"])
                and row["state"] == "active"
                and row["xact_start"]
                and datetime.fromisoformat(row["xact_start"]).timestamp() >= epoch
                and row["leader_pid"] is None
            ]
            if len(candidates) > 1:
                raise RuntimeError("ambiguous_retry_identity")
            if candidates:
                observed = candidates[0]
                if target and not (
                    target["pid"] == observed["pid"]
                    and same_time(target["backend_start"], observed["backend_start"])
                    and same_time(target["xact_start"], observed["xact_start"])
                ):
                    raise RuntimeError("retry_transaction_changed")
                target = observed
            emit(
                "retry_sample",
                elapsed_s=round(time.time() - epoch, 3),
                snapshot=latest,
                host=host_counters(),
                target_process=process_counters(target["pid"]) if target else None,
                clock_ticks_per_second=os.sysconf("SC_CLK_TCK"),
            )
            next_sample = time.monotonic() + min(
                15, max(0, PAGE_LIMIT - (time.time() - epoch))
            )
            if time.time() - epoch >= PAGE_LIMIT and not cancel_attempted:
                if not candidates or not candidates[0]["hudu"]:
                    raise RuntimeError("deadline_target_not_identified")
                cancel(target, "retry_measurement_limit")
                cancel_attempted = True
    finally:
        # Also clean up the attributed retry on collector errors/client timeout.
        final = sql(SNAPSHOT)
        if target and transaction_active(final, target):
            current = next(
                row for row in final["sessions"] if row["pid"] == target["pid"]
            )
            if current["hudu"] and not cancel_attempted:
                cancel(current, "retry_cleanup")
                time.sleep(1)
                final = sql(SNAPSHOT)
        closed = None if target is None else not transaction_active(final, target)
        emit(
            "retry_verified",
            attributed=target is not None,
            transaction_closed=closed,
            snapshot=final,
        )
        status = client.wait(timeout=30)
        emit("retry_finished", http_exit=status, transaction_closed=closed)
    return 0 if closed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(http() if sys.argv[1:] == ["http"] else host())
    except Exception as error:
        emit("collector_failed", error=type(error).__name__)
        raise SystemExit(1) from None
