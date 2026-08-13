"""LOLRMM corpus ingest and exact local-product identity projection.

LOLRMM is a vetted corpus of RMM/RAT tools, but it has no local product UUID,
MSI ProductCode, or publisher identity that can be joined directly to our
catalog. It therefore never makes a fuzzy assertion. A normalized tool name
may become alertable only when it maps one-to-one to a normalized local product
name. Any duplicate in either corpus becomes candidate evidence instead.

The feed is fetched as a repository archive so a full, parsed corpus is the
unit of truth. A download, archive, or YAML parse failure raises before any
mutation; prior evidence is consequently never withdrawn by a partial corpus.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections import defaultdict

import httpx
import yaml

from ingest import db
from ingest.config import settings
from ingest.intel.status import record_run

log = logging.getLogger(__name__)

_ARCHIVE_URL = "https://codeload.github.com/magicsword-io/LOLRMM/zip/refs/heads/main"
_SOURCE_REF = "https://github.com/magicsword-io/LOLRMM"
_TIMEOUT = 60.0
_MATCHER_VERSION = "lolrmm/1"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def run_once() -> int:
    if not (settings.INTEL_ENABLED and settings.INTEL_LOLRMM_ENABLED):
        log.info("LOLRMM ingest disabled by flag; skipping")
        return 0
    with record_run("lolrmm") as state:
        tools = _fetch_complete_corpus()
        corpus_rows = _replace_corpus(tools)
        machine_rows = _project_identities(tools)
        state["rows_touched"] = corpus_rows + machine_rows
        state["notes"] = (
            f"{len(tools)} unique normalized LOLRMM tool(s); "
            f"{corpus_rows} corpus row(s), {machine_rows} assertion row(s) touched."
        )
        return corpus_rows + machine_rows


def _fetch_complete_corpus() -> dict[str, dict]:
    response = httpx.get(_ARCHIVE_URL, timeout=_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("LOLRMM archive was not a valid zip") from exc

    records: dict[str, dict] = {}
    duplicates: set[str] = set()
    yaml_files = [name for name in archive.namelist() if "/yaml/" in name and name.endswith((".yaml", ".yml"))]
    if not yaml_files:
        raise RuntimeError("LOLRMM archive contained no yaml corpus files")
    for filename in yaml_files:
        try:
            record = yaml.safe_load(archive.read(filename))
        except Exception as exc:
            raise RuntimeError(f"LOLRMM record could not be parsed: {filename}") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"LOLRMM record is not an object: {filename}")
        name = str(record.get("Name") or "").strip()
        category = str(record.get("Category") or "").strip().upper()
        if not name or category not in {"RMM", "RAT"}:
            raise RuntimeError(f"LOLRMM record is missing Name/Category: {filename}")
        normalized = _normalize(name)
        if not normalized:
            raise RuntimeError(f"LOLRMM record normalized to empty: {filename}")
        # LOLRMM evidences `remote_access`, never `rmm`, whatever its own
        # Category says. The corpus is "tools abused for unattended remote
        # access", which is what our `remote_access` means; its RMM/RAT split
        # describes vendor legitimacy, not capability. Mapping Category
        # straight through asserted `rmm` on TeamViewer, ScreenConnect,
        # AnyDesk, LogMeIn and GoToMyPC at the alertable tier, contradicting
        # the vetted rules that deliberately call those remote_access, so one
        # install raised both unauthorized_rmm and unauthorized_remote_access.
        # `rmm` means full endpoint management -- patching, scripting,
        # monitoring -- which a name match against this corpus cannot show.
        # Category is still validated above and kept verbatim in raw_record.
        capability = "remote_access"
        data = {
            "display_name": name,
            "capability": capability,
            "source_ref": f"{_SOURCE_REF}/blob/main/{filename.split('/', 1)[1]}",
            "raw_record": record,
        }
        if normalized in records:
            duplicates.add(normalized)
        else:
            records[normalized] = data
    # Preserve duplicates as a deliberate collision: the identity projector
    # will emit candidate-only evidence for a corresponding local product.
    for normalized in duplicates:
        records[normalized]["duplicate_corpus_name"] = True
    return records


def _replace_corpus(tools: dict[str, dict]) -> int:
    rows = [
        (normalized, data["display_name"], data["capability"], data["source_ref"], json.dumps(data["raw_record"]))
        for normalized, data in tools.items()
    ]
    with db.transaction() as cur:
        cur.executemany(
            """
            INSERT INTO catalog.lolrmm_tool
                (normalized_name, display_name, capability, source_ref, raw_record, updated_at,
                 withdrawn_at, withdrawn_reason)
            VALUES (%s, %s, %s, %s, %s::jsonb, now(), NULL, '')
            ON CONFLICT (normalized_name) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                capability = EXCLUDED.capability,
                source_ref = EXCLUDED.source_ref,
                raw_record = EXCLUDED.raw_record,
                updated_at = now(),
                withdrawn_at = NULL,
                withdrawn_reason = ''
            """,
            rows,
        )
        cur.execute(
            """
            UPDATE catalog.lolrmm_tool
               SET withdrawn_at = now(), withdrawn_reason = 'absent from complete LOLRMM corpus'
             WHERE withdrawn_at IS NULL
               AND NOT (normalized_name = ANY(%s::text[]))
            """,
            (list(tools),),
        )
        return len(rows) + (cur.rowcount or 0)


def _project_identities(tools: dict[str, dict]) -> int:
    """Emit vetted evidence only for one-to-one exact normalized identities."""
    with db.transaction() as cur:
        cur.execute("SELECT product_uuid, canonical_name FROM catalog.products")
        products_by_name: dict[str, list] = defaultdict(list)
        for product_uuid, canonical_name in cur.fetchall():
            normalized = _normalize(canonical_name)
            if normalized:
                products_by_name[normalized].append(product_uuid)

        desired: list[tuple] = []
        for normalized, tool in tools.items():
            matching_products = products_by_name.get(normalized, [])
            if not matching_products:
                continue
            source = "lolrmm"
            if tool.get("duplicate_corpus_name") or len(matching_products) != 1:
                source = "lolrmm_candidate"
            for product_uuid in matching_products:
                desired.append((
                    product_uuid, tool["capability"], source,
                    1.0 if source == "lolrmm" else 0.6,
                    "lolrmm.exact_normalized" if source == "lolrmm" else "lolrmm.normalization_collision",
                    tool["source_ref"], _MATCHER_VERSION,
                ))

        # Keep the desired set deliberately narrow.  Copying the assertion
        # table with CREATE TABLE AS would couple this connector to its
        # identity, timestamps, grants, and future columns.
        cur.execute(
            """
            CREATE TEMP TABLE lolrmm_desired (
                product_uuid uuid NOT NULL,
                capability text NOT NULL,
                source_key text NOT NULL,
                confidence numeric(4,3) NOT NULL,
                evidence_kind text NOT NULL,
                evidence_ref text NOT NULL,
                matcher_version text NOT NULL
            ) ON COMMIT DROP
            """
        )
        if desired:
            cur.executemany(
                """
                INSERT INTO lolrmm_desired
                    (product_uuid, capability, source_key, confidence, evidence_kind,
                     evidence_ref, matcher_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                desired,
            )
        cur.execute(
            """
            INSERT INTO catalog.capability_assertion_machine
                (product_uuid, capability, source_key, confidence, evidence_kind,
                 evidence_ref, matcher_version)
            SELECT product_uuid, capability, source_key, confidence, evidence_kind,
                   evidence_ref, matcher_version
              FROM lolrmm_desired
            ON CONFLICT (product_uuid, capability, source_key) WHERE withdrawn_at IS NULL
            DO UPDATE SET last_observed_at = now(), confidence = EXCLUDED.confidence,
                          evidence_kind = EXCLUDED.evidence_kind,
                          evidence_ref = EXCLUDED.evidence_ref,
                          matcher_version = EXCLUDED.matcher_version
            """
        )
        written = cur.rowcount or 0
        cur.execute(
            """
            UPDATE catalog.capability_assertion_machine m
               SET withdrawn_at = now(),
                   withdrawn_reason = 'no longer matched by complete LOLRMM corpus'
             WHERE m.withdrawn_at IS NULL
               AND m.source_key IN ('lolrmm', 'lolrmm_candidate')
               AND NOT EXISTS (
                   SELECT 1 FROM lolrmm_desired d
                    WHERE d.product_uuid = m.product_uuid
                      AND d.capability = m.capability AND d.source_key = m.source_key
               )
            """
        )
        return written + (cur.rowcount or 0)
