"""Approval-gated release acceptance: four sequential GETs, no response content.

Run by path beside the reviewed plan056_http_pilot.py authentication helper.
First/repeat requests do not establish worker identity or cache state.
"""

from __future__ import annotations

import signal
import time

from plan056_http_pilot import emit, main


def measure(request, prefix):
    emit(
        "release_scope",
        prefix=prefix,
        role="configured_admin",
        max_gets=4,
        deadline_s=20,
        cache="unknown_worker_and_cache",
    )
    index = 0
    for route in ("/", "/inventory/computers/"):
        for repeat in (False, True):
            index += 1
            marker = f"{prefix}_{index}"
            emit("page_start", marker=marker, route=route, repeat=repeat)

            def deadline(signum, frame):
                raise TimeoutError()

            signal.signal(signal.SIGALRM, deadline)
            signal.setitimer(signal.ITIMER_REAL, 20)
            started = time.monotonic()
            succeeded = False
            try:
                with request(f"{route}?_plan056={marker}") as response:
                    headers_s = time.monotonic() - started
                    size = 0
                    while chunk := response.read(65536):
                        size += len(chunk)
                    succeeded = response.status == 200
                    emit(
                        "page",
                        marker=marker,
                        route=route,
                        repeat=repeat,
                        status=response.status,
                        headers_s=round(headers_s, 3),
                        elapsed_s=round(time.monotonic() - started, 3),
                        bytes=size,
                    )
            except Exception as error:
                emit(
                    "page_incomplete",
                    marker=marker,
                    route=route,
                    repeat=repeat,
                    error=type(error).__name__,
                    elapsed_s=round(time.monotonic() - started, 3),
                    server_completion="unverified",
                )
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            if not succeeded:
                emit("stopped", reason="page_failed_no_more_gets", marker=marker)
                return 1
    emit("release_pages_complete", gets=index)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(measure))
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
