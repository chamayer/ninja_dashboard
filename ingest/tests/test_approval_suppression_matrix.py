"""Approval silences trust questions, never facts.

The retired per-installation classifier (`software_findings.py`) skipped every
rule for an approved installation:

    dec = _resolve_decision(...)
    if dec in ("approve", "approve_publisher"):
        continue  # approved, skip all rules

So approving a title also silenced its CVEs, its threat-intel hits, its
end-of-life state and its suspicious install path. `vulnerable_software` and
`known_malicious_hint` re-tested the decision locally as well, so they were
suppressed twice and removing the loop-head skip alone would not have freed
them.

Approval means "this software is allowed here" — a statement about trust. It
cannot make a fact untrue. Which findings it may silence is a per-type registry
row (`finding_types.suppressed_by_approval`, migration 0136), not a constant in
the emitter: it maps a domain value to a behavior, which ADR-0012 section 6
requires to be data and which `test_no_hardcoded_domain_mappings` would flag.

The rebuilt findings run (`software_reconcile.py`) keeps the rule: an
approval silences a type only when its registry row says so (`silenced`).

These tests are a ratchet. The failure they prevent is silent: a re-introduced
blanket skip suppresses security findings without erroring, and the only symptom
is findings that quietly never appear.
"""

from __future__ import annotations

import re
from pathlib import Path

from ingest import software_reconcile as sr

_ROOT = Path(__file__).resolve().parents[2]
_RECONCILE = _ROOT / "ingest" / "software_reconcile.py"
_CAPABILITIES = _ROOT / "ingest" / "software_capabilities.py"
_MIGRATION = (
    _ROOT / "operations" / "apps" / "core" / "migrations"
    / "0136_finding_type_suppressed_by_approval.py"
)

# Findings that assert something about the software itself.
_FACTUAL = (
    "vulnerable_software",
    "known_malicious_hint",
    "eol_runtime",
    "install_path_suspicious",
)
# Findings that are trust questions, which approval legitimately answers.
_TRUST = (
    "unauthorized_av",
    "unauthorized_rmm",
    "unauthorized_remote_access",
    "whitelist_suggestion",
    "suspicious_name",
    "rare_recent",
)


def _type(name: str, suppressed: bool) -> sr.FindingType:
    return sr.FindingType(1, name, "software_product", suppressed, False, "high", True)


def _code_only(path: Path) -> str:
    """Comments quote the removed skip in order to explain it."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_approval_silences_only_where_the_registry_says_so() -> None:
    fact, trust = _type("vulnerable_software", False), _type("unauthorized_av", True)
    # Not approved: nothing is silenced.
    for finding_type in (fact, trust):
        assert sr.silenced(finding_type, None, None, False) is False
    # Approved title: the registry decides.
    assert sr.silenced(fact, "approve", None, False) is False
    assert sr.silenced(trust, "approve", None, False) is True
    # A publisher approval silences a trust question only without another concern.
    assert sr.silenced(trust, None, "approve_publisher", False) is True
    assert sr.silenced(trust, None, "approve_publisher", True) is False
    # A rejection never silences.
    assert sr.silenced(trust, "reject", None, False) is False


def test_no_blanket_skip_for_approved_software() -> None:
    code = _code_only(_RECONCILE)
    assert "continue  # approved, skip all rules" not in code
    assert not re.search(
        r'if\s+\w+\s+in\s+\("approve",\s*"approve_publisher"\)\s*:\s*\n\s*continue', code
    ), "a loop-head skip on approval suppresses every later detector"
    # The approval vocabulary is tested in one place, the registry-gated helper.
    assert code.count('("approve", "approve_publisher")') == 1


def test_multi_av_conflict_is_not_reconciled() -> None:
    """Disabled: installed packages cannot prove active protection. The
    findings run does not own the type, so an empty desired set never resolves
    its existing findings either."""
    code = _code_only(_RECONCILE)
    owned = code[code.index("owned = {"):code.index("}", code.index("owned = {"))]
    assert "multi_av_conflict" not in owned


def test_schema_readiness_uses_a_catalog_probe_not_an_exception() -> None:
    """Operations migrations are applied by a different container that starts
    concurrently, so ingest can meet a schema without a column. A failed
    statement aborts the transaction, and rolling back would discard
    `SET LOCAL operations.tenant_id`."""
    code = _code_only(_CAPABILITIES)
    assert "pg_attribute" in code and "to_regclass" in code
    assert "except psycopg" not in code
    assert ".rollback()" not in code


def test_migration_opens_exactly_the_factual_types() -> None:
    migration = _MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"_FACTUAL\s*=\s*\((.*?)\)", migration, re.DOTALL)
    assert match is not None
    listed = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert listed == set(_FACTUAL), listed
    # The trust findings must not be opened up by the same migration.
    for name in _TRUST:
        assert name not in listed, name


def test_migration_sets_false_not_true() -> None:
    """`suppressed_by_approval=False` is what un-silences a finding; the column
    defaults True so everything else is unchanged."""
    migration = _MIGRATION.read_text(encoding="utf-8")
    assert "update(suppressed_by_approval=False)" in migration
    assert "default=True" in migration
