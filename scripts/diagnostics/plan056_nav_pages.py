"""User-requested one-pass navigation timings; discard all response content."""

from __future__ import annotations

import signal
import time

from plan056_http_pilot import emit, main

ROUTES = (
    ("Dashboard", "/"),
    ("Issues", "/findings/"),
    ("Clients", "/orgs/all/"),
    ("Computers", "/devices/"),
    ("Patching", "/patching/"),
    ("Software", "/software/"),
    ("Inventory Clients", "/inventory/clients/"),
    ("Inventory Computers", "/inventory/computers/"),
    ("Inventory Source records", "/inventory/source-records/"),
    ("Admin Overview", "/admin/overview/"),
    ("Admin Data", "/admin/data/"),
    ("Admin Sources", "/sources/"),
    ("Admin Jobs", "/admin/jobs/?refresh=off"),
    ("Admin Health", "/admin/findings/health/"),
    ("Admin Settings", "/admin/settings/"),
)


def measure(request, prefix):
    emit("nav_scope", prefix=prefix, max_gets=len(ROUTES), deadline_s=20)
    for index, (label, route) in enumerate(ROUTES, 1):
        marker = f"{prefix}_{index}"
        emit("page_start", label=label, route=route, marker=marker)

        def deadline(signum, frame):
            raise TimeoutError()

        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, 20)
        started = time.monotonic()
        succeeded = False
        try:
            separator = "&" if "?" in route else "?"
            with request(f"{route}{separator}_plan056={marker}") as response:
                headers_s = time.monotonic() - started
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                succeeded = response.status == 200
                emit(
                    "page",
                    label=label,
                    route=route,
                    marker=marker,
                    status=response.status,
                    headers_s=round(headers_s, 3),
                    elapsed_s=round(time.monotonic() - started, 3),
                    bytes=size,
                )
        except Exception as error:
            emit(
                "page_incomplete",
                label=label,
                marker=marker,
                error=type(error).__name__,
                elapsed_s=round(time.monotonic() - started, 3),
            )
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        if not succeeded:
            emit("stopped", reason="page_failed_no_more_gets", marker=marker)
            return 1
    emit("nav_complete", gets=len(ROUTES))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(measure))
    except Exception as error:
        emit("setup_failed", error=type(error).__name__)
        raise SystemExit(1) from None
