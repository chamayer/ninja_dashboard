"""Approval silences trust questions, never facts.

`software_findings.py` used to skip every rule for an approved installation:

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

These tests are a ratchet. The failure they prevent is silent: a re-introduced
blanket skip suppresses security findings without erroring, and the only symptom
is findings that quietly never appear.
"""

from __future__ import annotations

import re
import pytest
from pathlib import Path

_EMITTER = Path(__file__).resolve().parents[1] / "software_findings.py"
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "operations" / "apps" / "core" / "migrations"
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


def _code_only() -> str:
    """Comments quote the removed skip in order to explain it."""
    return "\n".join(
        line for line in _EMITTER.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_no_blanket_skip_for_approved_software() -> None:
    code = _code_only()
    assert "continue  # approved, skip all rules" not in code
    # Any bare `continue` guarded only by the approval test is the same bug
    # wearing a different comment.
    assert not re.search(
        r'if\s+dec\s+in\s+\("approve",\s*"approve_publisher"\)\s*:\s*\n\s*continue',
        code,
    ), "a loop-head skip on approval suppresses every later detector"


def test_factual_findings_do_not_re_test_the_decision_locally() -> None:
    """vulnerable_software and known_malicious_hint each had their own
    `dec not in (...)` check, which would keep them suppressed even after the
    loop-head skip was removed."""
    code = _code_only()
    assert 'dec not in ("approve", "approve_publisher")' not in code


def test_approval_silences_executable_behavior() -> None:
    """Behavior, not source text — the ratchets above only read the file."""
    sf = pytest.importorskip("ingest.software_findings")
    matrix = {"vulnerable_software": False, "unauthorized_av": True}

    # Not approved: nothing is silenced, whatever the matrix says.
    for name in ("vulnerable_software", "unauthorized_av", "anything"):
        assert sf.approval_silences(name, False, matrix) is False, name

    # Approved: the matrix decides.
    assert sf.approval_silences("vulnerable_software", True, matrix) is False
    assert sf.approval_silences("unauthorized_av", True, matrix) is True

    # Unregistered type defaults to suppressed — the pre-0136 behavior, so a
    # newly added finding never starts firing for approved software by accident.
    assert sf.approval_silences("brand_new_finding", True, matrix) is True

    # Empty matrix is the schema-not-ready case: everything suppressed.
    assert sf.approval_silences("vulnerable_software", True, {}) is True


def test_multi_av_conflict_is_disabled_and_not_approval_gated() -> None:
    """Disabled: installed packages cannot prove active protection, and
    removing the old blanket skip would otherwise *expose* new occurrences,
    since that skip incidentally suppressed some. Not approval-gated either:
    it is device-wide while `dec` belongs to whichever installation the loop is
    on, so gating would make suppression row-order-dependent."""
    code = _code_only()
    assert 'approval_silences("multi_av_conflict"' not in code
    assert 'cfg.get("multi_av_conflict_enabled", False)' in code


class _FakeCursor:
    """Records statements and fails loudly if the transaction is discarded."""

    def __init__(self, *, column_present: bool) -> None:
        self.column_present = column_present
        self.statements: list[str] = []
        self._result: list[tuple] = []
        self.connection = self

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.statements.append(" ".join(sql.split()))
        if "pg_attribute" in sql:
            self._result = [(self.column_present,)]
        elif "suppressed_by_approval" in sql:
            self._result = [("vulnerable_software", "software_version", False)]
        else:
            self._result = [("vulnerable_software", "software_version")]

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return self._result

    def rollback(self):  # pragma: no cover - must never be reached
        raise AssertionError(
            "rollback() would discard SET LOCAL operations.tenant_id, so every "
            "later RLS-protected read returns nothing and the run reports a "
            "misleading successful zero-row pass"
        )


def test_legacy_schema_path_preserves_transaction_state() -> None:
    """The pre-0136 schema must not cost the transaction.

    A failed statement aborts the transaction, and recovering by rolling back
    would also discard `SET LOCAL operations.tenant_id`. The catalog probe
    avoids raising at all; this proves no rollback happens and the legacy query
    is used.
    """
    sf = pytest.importorskip("ingest.software_findings")
    cur = _FakeCursor(column_present=False)

    scopes, matrix = sf._load_scopes(cur)

    assert matrix == {}, "empty matrix means everything suppressed, as before 0136"
    assert scopes == {"vulnerable_software": "software_version"}
    joined = " | ".join(cur.statements)
    assert "pg_attribute" in joined, "must probe the catalog before querying"
    assert "suppressed_by_approval" not in joined.split("pg_attribute")[-1]


def test_current_schema_path_reads_the_matrix() -> None:
    sf = pytest.importorskip("ingest.software_findings")
    cur = _FakeCursor(column_present=True)

    scopes, matrix = sf._load_scopes(cur)

    assert matrix == {"vulnerable_software": False}
    assert scopes == {"vulnerable_software": "software_version"}


def test_every_finding_consults_the_registry() -> None:
    """Each finding is gated by the registry before it can emit.

    The three `unauthorized_*` types share one loop and are gated through the
    computed `finding_name`, so they are checked by that construct rather than
    by a literal.
    """
    code = _code_only()
    literally_gated = [n for n in _FACTUAL + _TRUST if not n.startswith("unauthorized_")]
    for name in literally_gated:
        assert f'approval_silences("{name}"' in code, name

    # The unauthorized_* types are emitted from effective capability evidence,
    # where the finding name comes from the capability row rather than a
    # literal. The property that matters is unchanged: the name is passed
    # through the registry gate before anything is emitted.
    assert "approval_silences(finding_name" in code

    # Called directly, not through a closure rebuilt for every installation.
    assert "def _silenced" not in code


def test_registry_default_preserves_previous_behavior() -> None:
    """An unregistered type must not silently start firing for approved
    software. `test_approval_silences_executable_behavior` is the authority
    here; this guards the default surviving a refactor of the helper."""
    code = _code_only()
    assert "matrix.get(finding_type, True)" in code


def test_schema_readiness_uses_a_catalog_probe_not_an_exception() -> None:
    """Operations migration 0136 is applied by a different container that
    starts concurrently, so ingest can meet a schema without the column.

    It must probe `pg_attribute` rather than letting the query fail: a failed
    statement aborts the transaction, and rolling back to recover would discard
    `SET LOCAL operations.tenant_id`.
    """
    code = _code_only()
    assert "pg_attribute" in code
    assert "to_regclass" in code
    assert "SELECT name, subject_scope FROM operations.finding_types" in code
    # Assert on the construct, not the word: the helper's docstring names the
    # rejected approach in order to explain it.
    assert "except psycopg" not in code, "catch-and-rollback costs the transaction"
    assert "connection.rollback()" not in code
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
