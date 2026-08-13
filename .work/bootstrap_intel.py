"""Bootstrap intel connectors — run once inside operations-ingest to
populate the intel layer immediately on first deploy without waiting
for the natural scheduler cadence.

Runs each connector SEQUENTIALLY in the foreground so the parent
process is still alive when each completes. Intended for
``docker exec -d ... python /tmp/bootstrap_intel.py`` (detached)
with logs viewable via ``docker exec ... cat /tmp/bootstrap_intel.log``.
"""

import logging
import sys
import time
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bootstrap_intel")

from ingest import db as _db
from ingest.config import settings as _settings

_db.init(_settings.postgres_dsn)

from ingest.intel import (  # noqa: E402
    abusech,
    chocolatey,
    cisa_kev,
    cpe_dict,
    epss,
    matcher,
    nvd,
    otx,
    winget,
)


def _step(name, fn):
    started = time.time()
    log.info("bootstrap: START %s", name)
    try:
        rows = fn()
    except Exception:
        log.error("bootstrap: FAIL %s\n%s", name, traceback.format_exc())
        return 0
    took = int(time.time() - started)
    log.info("bootstrap: DONE  %s rows=%s took=%ds", name, rows, took)
    return rows


_step("cisa_kev", cisa_kev.run_once)
_step("nvd", nvd.run_once)
_step("cpe_dict", cpe_dict.run_once)
_step("epss", epss.run_once)
_step("winget", winget.run_once)
_step("chocolatey", chocolatey.run_once)
_step("otx", otx.run_once)
_step("abusech", abusech.run_once)
# Matcher last so it sees populated cves + cpes.
_step("matcher", matcher.run_once)
log.info("bootstrap: ALL DONE")
