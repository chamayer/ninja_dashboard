"""One authenticated Source Records HTML baseline; emit no content."""
import time
from plan056_http_pilot import emit, main


def measure(request, prefix):
    started = time.monotonic()
    size = 0
    with request(f"/inventory/source-records/?_plan056={prefix}_1", timeout=30) as response:
        while chunk := response.read(65536):
            size += len(chunk)
        emit("source_records_page", status=response.status,
             elapsed_s=round(time.monotonic()-started, 3), bytes=size,
             scope="full_internal_http_html", values_discarded=True)
        return 0 if response.status == 200 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(measure))
    except Exception as error:
        emit("stopped", error=type(error).__name__)
        raise SystemExit(1) from None
