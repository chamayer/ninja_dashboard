"""One authenticated Software HTML check; emit timing/state only, no content."""

import time

from plan056_http_pilot import emit, main


def measure(request, prefix):
    started = time.monotonic()
    size = 0
    complete = False
    tail = b""
    with request(f"/software/?_plan056={prefix}_1") as response:
        while chunk := response.read(65536):
            size += len(chunk)
            complete = complete or b"Completed summary" in tail + chunk
            tail = chunk[-64:]
        elapsed = time.monotonic() - started
        emit(
            "software_page",
            status=response.status,
            elapsed_s=round(elapsed, 3),
            bytes=size,
            completed_summary=complete,
            ordinary_target_met=elapsed <= 1.5,
            hard_target_met=elapsed < 2,
            scope="full_internal_http_html",
            cache="first_observed_unknown",
            values_discarded=True,
        )
        return 0 if response.status == 200 and complete and elapsed < 2 else 1


if __name__ == "__main__":
    raise SystemExit(main(measure))
