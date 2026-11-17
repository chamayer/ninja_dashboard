"""Compare deployed and proposed Home installed-title counts without writes.

Run only in an explicitly authorized rehearsal or production environment. Copy
this file and the reviewed proposed software_review.py into the container first;
pass the latter's path as the sole argument. Output contains no software data.
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

from apps.core import software_review as deployed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python .plan044_software_parity_probe.py /path/to/software_review.py")
        return 2
    name = "apps.core.plan044_preview_software_review"
    spec = importlib.util.spec_from_file_location(name, sys.argv[1])
    if spec is None or spec.loader is None:
        print("preview module unavailable")
        return 2
    preview = importlib.util.module_from_spec(spec)
    sys.modules[name] = preview
    spec.loader.exec_module(preview)
    deployed_hash = hashlib.sha256(Path(deployed.__file__).read_bytes()).hexdigest()[:12]
    preview_hash = hashlib.sha256(Path(preview.__file__).read_bytes()).hexdigest()[:12]
    stage = "setup"
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL operations.tenant_id = 1")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            start = time.perf_counter()
            stage = "deployed"
            before = deployed.home_summary()
            deployed_seconds = time.perf_counter() - start
            start = time.perf_counter()
            stage = "preview"
            after = preview.home_summary()
            preview_seconds = time.perf_counter() - start
            matches = before["installed_titles"] == after["installed_titles"]
            print(
                f"installed_titles_match={matches} "
                f"deployed_seconds={deployed_seconds:.3f} "
                f"preview_seconds={preview_seconds:.3f} "
                f"deployed_sha256={deployed_hash} preview_sha256={preview_hash}"
            )
            return 0 if matches else 1
    except DatabaseError as error:
        cause = error.__cause__
        sqlstate = getattr(cause, "sqlstate", None) or getattr(error, "sqlstate", None) or "unknown"
        print(f"database_check_failed={type(error).__name__} stage={stage} sqlstate={sqlstate}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
