from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _ROOT / "operations" / "apps" / "core" / "migrations"
    / "0283_software_rules_and_finding_type_policy.py"
).read_text(encoding="utf-8")


def _forward_sql() -> str:
    return _MIGRATION[_MIGRATION.index('FORWARD_SQL = r"""') : _MIGRATION.index('REVERSE_SQL = r"""')]


def test_suggestion_rules_put_every_adverse_rule_before_any_favorable_one():
    rows = re.findall(r"\((\d+), '([a-z_]+)', (TRUE|FALSE), '([a-z_]+)'", _forward_sql())
    assert len(rows) == 8
    priorities = [int(row[0]) for row in rows]
    assert priorities == sorted(priorities)
    adverse = [row[2] == "TRUE" for row in rows]
    assert adverse == sorted(adverse, reverse=True)  # all TRUE first, then all FALSE
    assert rows[-1][1:] == ("fallback", "FALSE", "none")


def test_junk_publisher_patterns_compile_with_the_classifier_regex_engine():
    patterns = re.findall(r"\('junk_publisher', '((?:[^']|'')*)', TRUE", _forward_sql())
    assert len(patterns) == 5
    compiled = [re.compile(pattern.replace("''", "'"), re.IGNORECASE) for pattern in patterns]

    def junk(publisher: str) -> bool:
        return any(rule.search(publisher.lower()) for rule in compiled)

    for value in ("", "Your Company Name", "{4CEC2908-5CE4-48F0-A717-8FC833D8017A}", "N/A", "1234"):
        assert junk(value), value
    for value in ("Microsoft Corporation", "Adobe Inc.", "7-Zip", "linux"):
        assert not junk(value), value


def test_concern_flags_and_decision_scope_are_seeded_as_data():
    sql = _forward_sql()
    concerns = sql[sql.index("SET concern_signal = TRUE") : sql.index(");", sql.index("SET concern_signal = TRUE"))]
    for name in ("suspicious_name", "install_path_suspicious", "known_malicious_hint", "rare_recent"):
        assert f"'{name}'" in concerns
    for name in ("vulnerable_software", "eol_runtime", "whitelist_suggestion"):
        assert f"'{name}'" not in concerns
    assert "SET default_decision_scope = 'device' WHERE name = 'rare_recent'" in sql


def test_rule_tables_have_an_admin_surface():
    admin = (_ROOT / "operations" / "apps" / "core" / "admin.py").read_text(encoding="utf-8")
    assert "@admin.register(SoftwareClassifierRule)" in admin
    assert "@admin.register(SoftwareSuggestionRule)" in admin
    assert '"concern_signal",' in admin and '"default_decision_scope",' in admin
