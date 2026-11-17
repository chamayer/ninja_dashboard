"""Compare deployed and proposed Home Issues readers without writing data.

Run only in an explicitly authorized rehearsal or production environment. Copy
this file and the reviewed proposed issue_selection.py into the container first;
pass the latter's path as the sole argument. Output contains no issue data.
"""

import hashlib
import importlib.util
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")

import django

django.setup()

from django.db import DatabaseError, connection, transaction

from apps.core import issue_selection as deployed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python .plan044_issue_parity_probe.py /path/to/issue_selection.py")
        return 2
    name = "apps.core.plan044_preview_issue_selection"
    spec = importlib.util.spec_from_file_location(name, sys.argv[1])
    if spec is None or spec.loader is None:
        print("preview module unavailable")
        return 2
    preview = importlib.util.module_from_spec(spec)
    sys.modules[name] = preview
    spec.loader.exec_module(preview)
    deployed_hash = hashlib.sha256(Path(deployed.__file__).read_bytes()).hexdigest()[:12]
    preview_hash = hashlib.sha256(Path(preview.__file__).read_bytes()).hexdigest()[:12]
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id = 1")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            start = time.perf_counter()
            before = deployed.home_data()
            deployed_seconds = time.perf_counter() - start
            start = time.perf_counter()
            after = preview.home_data()
            preview_seconds = time.perf_counter() - start
            print(
                f"match={before == after} "
                f"deployed_seconds={deployed_seconds:.3f} "
                f"preview_seconds={preview_seconds:.3f} "
                f"deployed_sha256={deployed_hash} preview_sha256={preview_hash}"
            )
            return 0 if before == after else 1
    except DatabaseError as error:
        print(f"database_check_failed={type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
