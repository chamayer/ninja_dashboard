# Performance diagnostic source

Retained PLAN-056 evidence collectors and historical recovery scripts. These
files are not copied into runtime images or invoked by service entrypoints.
The linked plan/record owns each script's original scope and results; filenames
and old approval text do not authorize a new execution.

Review a script and its current target before any use. Several historical
emergency scripts cancel Jobs/backends, request work, publish results or send
signals; these require explicit authorization for the identified live action.
Never replay old run IDs or backend/process IDs as current authority. HTTP
collectors perform normal login/logout and must protect credentials in memory.

`archive/plan044/` preserves the eight former root `.plan044_*_probe.py` files.
They are historical source, not ready-to-run recovery tools. Older records keep
their original names for provenance. Do not run them unchanged against live data.

Use the repository's remote-execution rules: review/copy a Python file and invoke
it by path, or use a packaged module. No Python source injection through commands
or stdin. Keep output free of credentials and customer payloads.
