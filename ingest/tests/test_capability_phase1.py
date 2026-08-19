"""Phase 1 contracts: authority, precedence, write boundary, withdrawal safety.

Structural where a database is required (no production access is authorized for
this phase) and executable where the logic is in Python. Each test names the
failure it prevents, because most of them fail silently rather than loudly:
a widened withdrawal deletes evidence, a drifted precedence rule alerts on a
refuted capability, and a self-promoting source turns a community tag into a
security finding.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "sql" / "migrations" / "093_capability_assertions.sql"
_PROJECTOR = _ROOT / "ingest" / "intel" / "capability_match.py"


def _sql() -> str:
    """Migration text with `--` comments removed.

    The comments deliberately name the mechanisms being rejected in order to
    explain them, so a check that could not tell prose from DDL would force the
    explanations to be deleted to stay green.
    """
    raw = _MIGRATION.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())


def _sql_with_comments() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _projector_code() -> str:
    """Projector source with `#` comments and docstrings removed."""
    raw = _PROJECTOR.read_text(encoding="utf-8")
    without_docstrings = re.sub(r'"""."*?"""', "", raw, flags=re.DOTALL)
    return "\n".join(
        line for line in without_docstrings.splitlines()
        if not line.lstrip().startswith("#")
    )


def _projector_sql_literals() -> str:
    """Only the SQL constants the projector executes.

    Matches `_NAME_SQL = \"\"\"...\"\"\"` specifically, so the module docstring --
    which names the tables this projector must not touch, in order to say so --
    is not mistaken for executed SQL.
    """
    raw = _PROJECTOR.read_text(encoding="utf-8")
    return "\n".join(
        re.findall(r'^_\w+_SQL\s*=\s*"""(.*?)"""', raw, flags=re.DOTALL | re.MULTILINE)
    )


# ── Contract 1: authority is registry-owned ─────────────────────────────────

def test_may_alert_cannot_be_set_independently_of_authority() -> None:
    """A later UPDATE must not be able to promote a community tag to alerting."""
    sql = _sql()
    assert "ck_capability_source_may_alert" in sql
    assert "may_alert = (authority_class IN" in sql


def test_only_vetted_classes_may_alert() -> None:
    sql = _sql()
    match = re.search(
        r"may_alert = \(authority_class IN \((.*?)\)\)", sql, re.DOTALL
    )
    assert match is not None
    allowed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert allowed == {"vetted_identity", "vetted_rule"}


def test_machine_cannot_impersonate_an_operator() -> None:
    """`capability_assertion_machine.source_key` is a FK to this registry, so an
    'operator' row here would let any machine writer manufacture alertable
    evidence. Operator precedence comes from the operator *table*."""
    sql = _sql()
    registry = sql[
        sql.index("CREATE TABLE IF NOT EXISTS catalog.capability_source"):
        sql.index("CREATE TABLE IF NOT EXISTS catalog.capability_assertion_machine")
    ]
    assert "'operator'" not in registry, "no operator row, and no operator class"
    classes = re.search(
        r"authority_class IN \((.*?)\)\s*\)", registry, re.DOTALL
    )
    assert classes is not None
    assert "operator" not in set(re.findall(r"'([a-z_]+)'", classes.group(1)))


def test_community_sources_are_seeded_non_alerting() -> None:
    sql = _sql()
    for source in ("winget_tag", "chocolatey_tag", "publisher_rule"):
        row = re.search(rf"'{source}',\s*'[a-z_]+',\s*(TRUE|FALSE)", sql)
        assert row is not None, source
        assert row.group(1) == "FALSE", source


def test_projector_does_not_write_authority() -> None:
    """The projector may report confidence and evidence, never may_alert."""
    executed_sql = _projector_sql_literals()
    assert "may_alert" not in executed_sql
    assert "capability_source" not in executed_sql


# ── Contract 2: effective precedence ────────────────────────────────────────

def test_operator_negative_overrides_machine_evidence() -> None:
    sql = _sql()
    assert "WHEN o.polarity IS FALSE THEN 'refuted'" in sql
    # A refuted capability must never be alertable, whatever machines assert.
    assert "(o.polarity IS TRUE" in sql
    assert "o.polarity IS NULL AND COALESCE(m.has_alertable_source, FALSE)" in sql


def test_unknown_is_absence_not_a_row() -> None:
    """No assertion means unknown; the view must not manufacture a row."""
    sql = _sql()
    assert "FULL OUTER JOIN" in sql
    assert "no row means unknown" in sql.lower() or "means unknown" in sql.lower()


def test_effective_relation_excludes_withdrawn() -> None:
    sql = _sql()
    view = sql[sql.index("CREATE OR REPLACE VIEW"):]
    assert view.count("withdrawn_at IS NULL") >= 2, (
        "both operator and machine sides must exclude withdrawn evidence"
    )


# ── Contract 1/5: write boundary and ownership ──────────────────────────────

def test_operations_cannot_write_machine_evidence() -> None:
    sql = _sql()
    assert re.search(
        r"REVOKE INSERT, UPDATE, DELETE, TRUNCATE\s*\n?\s*ON catalog\."
        r"capability_assertion_machine FROM operations_app",
        sql,
    )


def test_ingest_is_revoked_from_operator_assertions() -> None:
    """Currently inert -- ingest connects as a superuser -- but correct, and it
    begins enforcing the moment ingest runs as a non-superuser role."""
    sql = _sql()
    assert re.search(
        r"REVOKE INSERT, UPDATE, DELETE, TRUNCATE\s*\n?\s*ON catalog\."
        r"capability_assertion_operator FROM ninja_ingest",
        sql,
    )


def test_the_superuser_limitation_is_documented_not_hidden() -> None:
    """Claiming a boundary the database does not provide would be worse than
    the asymmetry. AGENTS.md: state a rule with its enforcement or not at all."""
    sql = _sql_with_comments().lower()
    assert "superuser" in sql
    assert "not enforceable" in sql


def test_nothing_may_delete_evidence() -> None:
    sql = _sql()
    assert re.search(r"REVOKE DELETE, TRUNCATE\s*\n?\s*ON catalog\."
                     r"capability_assertion_machine, catalog\."
                     r"capability_assertion_operator", sql)


# ── Withdrawal safety ───────────────────────────────────────────────────────

def test_empty_rule_set_does_not_withdraw_everything() -> None:
    """A rule table that failed to load looks exactly like one that matched
    nothing. Treating them alike would withdraw the whole corpus. Two
    independent guards -- pattern rules and tag rules -- so one empty table
    cannot block the other's pass."""
    code = _projector_code()
    assert "if rule_count == 0:" in code
    assert "if tag_count == 0:" in code


def test_evaluated_sources_come_from_loaded_rules_not_from_output() -> None:
    """A source whose rules all stop matching must still withdraw its stale
    assertions. Deriving `evaluated` from the output would leave them current
    forever, asserting a capability no rule supports."""
    code = _projector_code()
    assert "FROM catalog.capability_rule" in code
    assert "SELECT DISTINCT source_key FROM capability_desired" not in code
    # The withdraw statement is still scoped to those sources.
    assert "m.source_key = ANY(%s::text[])" in _projector_sql_literals()


def test_rule_collisions_are_collapsed_deterministically() -> None:
    """Two rules matching one product would make the upsert touch the same
    unique row twice -- PostgreSQL raises a cardinality violation and the whole
    projection fails."""
    sql = _projector_sql_literals()
    assert "DISTINCT ON (product_uuid, capability, source_key)" in sql
    # Precedence must be total, or two runs over unchanged data can disagree.
    assert "ORDER BY product_uuid, capability, source_key, specificity DESC, priority, rule_key" in sql


def test_rule_priority_is_actually_used() -> None:
    assert "priority" in _projector_sql_literals()


def test_disabled_sources_leave_effective_truth() -> None:
    """Filtering only inside has_alertable_source would downgrade a disabled
    source's evidence to a candidate rather than removing it."""
    sql = _sql()
    machine_cte = sql[sql.index("machine_current AS ("):sql.index("SELECT\n    COALESCE")]
    assert "AND s.enabled" in machine_cte
    assert "bool_or(s.may_alert)" in machine_cte


def test_operator_conclusions_are_immutable() -> None:
    """Table-level UPDATE would let Operations rewrite polarity, actor or
    timestamp in place, leaving no trace a human said something different."""
    sql = _sql()
    assert "GRANT SELECT, INSERT ON catalog.capability_assertion_operator" in sql
    assert re.search(
        r"GRANT UPDATE \(withdrawn_at, withdrawn_reason\)\s*\n?\s*"
        r"ON catalog\.capability_assertion_operator TO operations_app",
        sql,
    )
    assert "GRANT SELECT, INSERT, UPDATE ON catalog.capability_assertion_operator" not in sql


def test_rules_cannot_claim_an_unrelated_source() -> None:
    sql = _sql()
    assert "ck_capability_rule_source" in sql
    assert "source_key IN ('vetted_rule', 'publisher_rule')" in sql


def test_publisher_only_rules_cannot_be_vetted() -> None:
    """A rule matching only `Microsoft%` claiming vetted_rule would raise
    unauthorized findings across a publisher's entire catalog."""
    sql = _sql()
    assert "ck_capability_rule_vetted_needs_a_title" in sql
    assert "source_key <> 'vetted_rule' OR title_pattern <> ''" in sql


def test_both_sql_wildcards_are_rejected_as_anchors() -> None:
    """`_` matches one character, so '_hrome' is as loose as '%chrome'."""
    sql = _sql()
    anchored = sql[sql.index("ck_capability_rule_anchored"):]
    assert "NOT LIKE '\\%%'" in anchored
    assert "NOT LIKE '\\_%'" in anchored


def test_projector_never_touches_operator_or_foreign_sources() -> None:
    """A clear that reached operator rows would delete evidence the projector
    cannot rebuild."""
    assert "capability_assertion_operator" not in _projector_sql_literals()
    code = _projector_code()
    owned = re.search(r"_OWNED_SOURCES = \((.*?)\)", code, re.DOTALL)
    assert owned is not None
    assert set(re.findall(r'"([a-z_]+)"', owned.group(1))) == {
        "vetted_rule", "publisher_rule"
    }


def test_withdrawal_records_a_reason() -> None:
    """ADR-0012: nothing is lost without when and why."""
    sql = _sql()
    assert "ck_cam_withdrawn_reason" in sql
    assert "ck_cao_withdrawn_reason" in sql
    assert "withdrawn_reason = 'no longer matched by '" in _projector_code()


# ── Idempotency ─────────────────────────────────────────────────────────────

def test_write_is_an_upsert_not_an_insert() -> None:
    """A second run must not duplicate evidence or move first_observed_at."""
    code = _projector_code()
    assert "ON CONFLICT (product_uuid, capability, source_key)" in code
    assert "WHERE withdrawn_at IS NULL" in code
    assert "first_observed_at" not in code.split("DO UPDATE SET")[1].split('"""')[0]


def test_current_row_uniqueness_is_partial() -> None:
    """Withdrawn rows are history and may repeat, so a capability that goes
    away and returns leaves both episodes visible."""
    sql = _sql()
    assert "uq_cam_current" in sql
    assert "uq_cao_current" in sql
    idx = sql[sql.index("uq_cam_current"):]
    assert "WHERE withdrawn_at IS NULL" in idx


# ── Machine evidence is positive-only ───────────────────────────────────────

def test_machine_table_has_no_polarity() -> None:
    """Only an operator may assert a negative; that is what stops a rejected
    candidate reappearing every cycle."""
    sql = _sql()
    machine = sql[
        sql.index("CREATE TABLE IF NOT EXISTS catalog.capability_assertion_machine"):
        sql.index("CREATE TABLE IF NOT EXISTS catalog.capability_assertion_operator")
    ]
    assert "polarity" not in machine
    operator = sql[
        sql.index("CREATE TABLE IF NOT EXISTS catalog.capability_assertion_operator"):
    ]
    assert "polarity         boolean NOT NULL" in operator


# ── Rules are anchored ──────────────────────────────────────────────────────

def test_rules_cannot_use_a_leading_wildcard() -> None:
    """A loose pattern is how a title inherits the wrong capability -- the EOL
    work measured `Intel(R) Trusted Connect` matching `rust`."""
    sql = _sql()
    assert "ck_capability_rule_anchored" in sql


def test_projector_does_not_fuzzy_match() -> None:
    code = _projector_code()
    assert "difflib" not in code
    assert "SequenceMatcher" not in code


# ── Vocabulary is data ──────────────────────────────────────────────────────

def test_capability_vocabulary_is_a_table_not_a_check_constraint() -> None:
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS catalog.capability (" in sql
    assert "REFERENCES catalog.capability (key)" in sql


def test_capability_is_named_endpoint_security_not_av() -> None:
    """Installed inventory cannot prove an active protection engine."""
    sql = _sql()
    assert "'endpoint_security'" in sql


def test_config_flag_and_cadence_exist() -> None:
    config = (_ROOT / "ingest" / "config.py").read_text(encoding="utf-8")
    assert "INTEL_CAPABILITY_ENABLED" in config
    assert "INTEL_CAPABILITY_SCHEDULE_HOURS" in config


def test_projector_is_flag_gated() -> None:
    code = _projector_code()
    assert "settings.INTEL_CAPABILITY_ENABLED" in code


def test_projector_records_its_run() -> None:
    """record_run now captures duration (migration 090), so this projector's
    cost is visible from the first run."""
    code = _projector_code()
    assert 'record_run("capability_match")' in code


def test_matcher_version_is_stamped() -> None:
    """An assertion must say which matcher produced it, or a rule change cannot
    be told from a data change."""
    code = _projector_code()
    assert "MATCHER_VERSION" in code
    sql = _sql()
    assert "matcher_version   text    NOT NULL" in sql


def test_enforcement_is_explicitly_gated() -> None:
    """The classifier may consume effective evidence only behind Phase 4's
    separately reviewed enablement gate."""
    emitter = (_ROOT / "ingest" / "software_findings.py").read_text(encoding="utf-8")
    config = (_ROOT / "ingest" / "config.py").read_text(encoding="utf-8")
    assert "v_product_capability_effective" in emitter
    assert "CAPABILITY_ENFORCEMENT_ENABLED" in emitter
    assert "CAPABILITY_ENFORCEMENT_ENABLED: bool = False" in config


@pytest.mark.parametrize("name", ["endpoint_security", "rmm", "remote_access"])
def test_three_capabilities_seeded(name: str) -> None:
    assert f"('{name}'," in _sql()


# ── Tag-based evidence path (migration 106) ─────────────────────────────────

_TAG_MIGRATION = _ROOT / "sql" / "migrations" / "106_capability_tag_rule.sql"


def _tag_sql() -> str:
    raw = _TAG_MIGRATION.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"--.*$", "", line) for line in raw.splitlines())


def test_tag_rule_table_is_migration_managed_only() -> None:
    """No runtime writer for vocabulary, same as capability_rule."""
    sql = _tag_sql()
    assert re.search(
        r"REVOKE INSERT, UPDATE, DELETE, TRUNCATE\s*\n?\s*ON catalog\."
        r"capability_tag_rule\s*\n?\s*FROM operations_app, ninja_ingest",
        sql,
    )


def test_tag_rule_tags_are_lowercase_only() -> None:
    sql = _tag_sql()
    assert "ck_capability_tag_rule_tag_lower" in sql


def test_tag_rule_seed_is_evidence_backed_remote_access_only() -> None:
    """Seeded 2026-08-19 from real exact matches; endpoint_security and rmm
    get no rows here until a real match produces one."""
    sql = _tag_sql()
    for tag in ("rdp", "remote-control", "remote-desktop", "remote-access", "chromoting"):
        assert re.search(rf"'{tag}',\s*'remote_access'", sql), tag
    assert "'endpoint_security'" not in sql
    assert "'rmm'" not in sql


def test_tag_owned_sources_are_the_two_community_tag_registry_rows() -> None:
    code = _projector_code()
    owned = re.search(r"_TAG_OWNED_SOURCES = \((.*?)\)", code, re.DOTALL)
    assert owned is not None
    assert set(re.findall(r'"([a-z_]+)"', owned.group(1))) == {
        "winget_tag", "chocolatey_tag"
    }


def test_tag_pass_is_independent_of_the_rule_pass() -> None:
    """An empty (or not-yet-migrated) tag_rule table must not short-circuit
    the pattern-rule pass, and vice versa -- there is no single early return
    covering both."""
    code = _projector_code()
    assert "return 0, 0, 0, []" not in code
    assert code.index("if rule_count == 0:") < code.index("if tag_count == 0:")


def test_tag_write_does_not_move_first_observed_at() -> None:
    """A second run over unchanged tags must not duplicate evidence or move
    first_observed_at -- same upsert discipline as the rule-based write."""
    literals = _projector_sql_literals()
    tag_block = literals[literals.index("capability_tag_desired"):]
    assert "ON CONFLICT (product_uuid, capability, source_key)" in tag_block
    assert "first_observed_at" not in tag_block.split("DO UPDATE SET")[1].split(")")[0]
