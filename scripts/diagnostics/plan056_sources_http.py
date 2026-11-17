"""One authenticated Sources request, with no response values emitted."""
import time
from plan056_http_pilot import emit, main


def measure(request, prefix):
    started = time.monotonic()
    with request(f'/sources/?_plan056={prefix}_1', timeout=30) as response:
        size = sum(len(chunk) for chunk in iter(lambda: response.read(65536), b''))
        emit('sources_page', status=response.status, elapsed_s=round(time.monotonic()-started,3), bytes=size, values_discarded=True)
        return 0 if response.status == 200 else 1


if __name__ == '__main__':
    raise SystemExit(main(measure))
