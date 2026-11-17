"""Emit only worker job keys, process state and kernel waits, never arguments."""
import json
from collections import Counter
from pathlib import Path

for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        args = (entry/'cmdline').read_bytes().split(b'\0')
        if b'ingest.jobs_child' not in args and b'ingest.jobs_worker' not in args:
            continue
        marker = b'ingest.jobs_child' if b'ingest.jobs_child' in args else b'ingest.jobs_worker'
        key = args[args.index(marker)+1].decode() if marker.endswith(b'jobs_child') else 'supervisor'
        state = next(l for l in (entry/'status').read_text().splitlines() if l.startswith('State:'))
        waits = Counter((t/'wchan').read_text() for t in (entry/'task').iterdir())
        print(json.dumps({'pid':entry.name,'job':key,'state':state,'waits':dict(waits)}),flush=True)
    except (FileNotFoundError,PermissionError,ProcessLookupError):
        pass
