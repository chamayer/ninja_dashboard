"""Project the global software catalog from fleet installations.

`catalog.publishers` -> `catalog.products` -> `catalog.software_versions` are
global reference entities: software is not owned, so they carry no tenant and
live outside `operations.entities` (ADR-0012 s5 as amended 2026-08-10).

This is a **projector** in the `docs/glossary.md` sense -- deterministic,
rebuildable, sole writer, and safe to re-run. Drop the catalog and this
rebuilds it identically from the installations. It makes no identity decision
that a later run cannot correct.

Publisher normalization goes through `operations.publisher_aliases`, matched
with ILIKE -- the operator migration 0088 uses, since `raw_pattern` is a
pattern column, not a literal and not a regex. Measured 2026-08-07: aliases
cover 84% of installs but only 6% of distinct publishers, so the long tail
arrives unnormalized and collapses later as an operator adds aliases. That is
why re-running must stay cheap and non-destructive.

Nothing is deleted. A catalog entry whose last installation disappears is
still a real product, and removing it would break historical installations
pointing at it.

Known limits, recorded rather than papered over:

* `software_installations_current` has **no source column**, and its primary
  key is `(tenant, client, device, canonical_name)`. So two versions of one
  title on one device would collapse to a single row, and a second source
  reporting the same install has nowhere to go. Both are properties of that
  table, not of this projector. When a second software source appears,
  installations move to the observation pipeline and gain attribution and
  reconciliation there.
* The version collapse is **theoretical, not active loss**. Measured
  2026-08-10 against `software_installations_current` and the retained
  `software_installation_history` -- which carries `version` and is *not* keyed
  on it, so it is the only place the evidence could survive -- there are **0**
  (device, title) pairs with more than one distinct version. The catalog
  therefore loses nothing today. The key is not a defect to fix; re-derive this
  count before treating it as one.
"""

from __future__ import annotations

import logging

from ingest import db
from ingest.runlog import run_log

log = logging.getLogger(__name__)

TENANT_ID = 1
_GUC = f"SET LOCAL operations.tenant_id = {TENANT_ID}"
_BACKFILL_BATCH = 20000

# Resolve a raw publisher string to its canonical name. Repeated by each step
# rather than materialised, because the steps run as separate statements and a
# temp table would not survive them.
_RESOLVED_PUBLISHER = """
    LEFT JOIN LATERAL (
        SELECT alias.canonical_publisher
          FROM operations.publisher_aliases alias
         WHERE alias.enabled
           AND COALESCE(install.publisher, '') <> ''
           AND install.publisher ILIKE alias.raw_pattern
         LIMIT 1
    ) resolved ON TRUE
"""

_UPSERT_PUBLISHERS = f"""
INSERT INTO catalog.publishers (canonical_name)
SELECT DISTINCT COALESCE(resolved.canonical_publisher, install.publisher)
  FROM operations.software_installations_current install
  {_RESOLVED_PUBLISHER}
 WHERE COALESCE(install.publisher, '') <> ''
   AND install.deleted_at IS NULL
ON CONFLICT (canonical_name) DO NOTHING
"""

_UPSERT_PRODUCTS = f"""
INSERT INTO catalog.products (publisher_id, canonical_name)
SELECT DISTINCT publisher.id, install.canonical_name
  FROM operations.software_installations_current install
  {_RESOLVED_PUBLISHER}
  LEFT JOIN catalog.publishers publisher
    ON publisher.canonical_name
     = COALESCE(resolved.canonical_publisher, NULLIF(install.publisher, ''))
 WHERE install.deleted_at IS NULL
ON CONFLICT (publisher_id, canonical_name) DO NOTHING
"""

_UPSERT_VERSIONS = f"""
INSERT INTO catalog.software_versions (product_id, version)
SELECT DISTINCT product.id, COALESCE(install.version, '')
  FROM operations.software_installations_current install
  {_RESOLVED_PUBLISHER}
  LEFT JOIN catalog.publishers publisher
    ON publisher.canonical_name
     = COALESCE(resolved.canonical_publisher, NULLIF(install.publisher, ''))
  JOIN catalog.products product
    ON product.canonical_name = install.canonical_name
   AND product.publisher_id IS NOT DISTINCT FROM publisher.id
 WHERE install.deleted_at IS NULL
ON CONFLICT (product_id, version) DO NOTHING
"""

# Batched: 484,636 rows, and one UPDATE would hold row locks across the whole
# table while the software connector may be writing to it.
_BACKFILL_LINKS = f"""
WITH unlinked AS (
    SELECT install.tenant_id, install.client_id, install.device_id,
           install.canonical_name
      FROM operations.software_installations_current install
     WHERE install.software_version_id IS NULL
       AND install.deleted_at IS NULL
     LIMIT {_BACKFILL_BATCH}
     FOR UPDATE SKIP LOCKED
), resolved_rows AS (
    SELECT unlinked.tenant_id, unlinked.client_id, unlinked.device_id,
           unlinked.canonical_name, version.id AS software_version_id
      FROM unlinked
      JOIN operations.software_installations_current install
        ON install.tenant_id = unlinked.tenant_id
       AND install.client_id = unlinked.client_id
       AND install.device_id = unlinked.device_id
       AND install.canonical_name = unlinked.canonical_name
      {_RESOLVED_PUBLISHER}
      LEFT JOIN catalog.publishers publisher
        ON publisher.canonical_name
         = COALESCE(resolved.canonical_publisher, NULLIF(install.publisher, ''))
      JOIN catalog.products product
        ON product.canonical_name = install.canonical_name
       AND product.publisher_id IS NOT DISTINCT FROM publisher.id
      JOIN catalog.software_versions version
        ON version.product_id = product.id
       AND version.version = COALESCE(install.version, '')
)
UPDATE operations.software_installations_current target
   SET software_version_id = resolved_rows.software_version_id
  FROM resolved_rows
 WHERE target.tenant_id = resolved_rows.tenant_id
   AND target.client_id = resolved_rows.client_id
   AND target.device_id = resolved_rows.device_id
   AND target.canonical_name = resolved_rows.canonical_name
"""


def project_software_catalog() -> dict[str, int]:
    """Build the catalog and link installations to it. Safe to re-run."""
    with run_log("software.catalog") as stats:
        counts: dict[str, int] = {}
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(_GUC)
            cur.execute(_UPSERT_PUBLISHERS)
            counts["publishers_created"] = cur.rowcount
            cur.execute(_UPSERT_PRODUCTS)
            counts["products_created"] = cur.rowcount
            cur.execute(_UPSERT_VERSIONS)
            counts["versions_created"] = cur.rowcount

        linked = 0
        while True:
            # One transaction per batch, so a long backfill neither holds locks
            # nor loses completed work if it is interrupted.
            with db.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(_GUC)
                cur.execute(_BACKFILL_LINKS)
                written = cur.rowcount
            linked += written
            if written == 0:
                break
        counts["installations_linked"] = linked

        for key, value in counts.items():
            stats[key] = value
        log.info("software.catalog: %s", counts)
        return counts
