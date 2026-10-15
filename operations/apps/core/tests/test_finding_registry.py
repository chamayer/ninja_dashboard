"""The finding types registry: one name, category and group per type, and what covers it."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from apps.core import finding_registry, finding_types_admin
from apps.core.models import FindingType
from apps.core.templatetags import human_labels

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = importlib.import_module("apps.core.migrations.0295_finding_types_registry")
ROWS = _MIGRATION.ROWS


def _rows():
    return [
        {
            "name": name,
            "display_name": display,
            "issue_category": category,
            "issue_group": group,
            "sort_order": order,
            "covered_by": list(covered),
            "cover_note": note,
        }
        for name, display, category, group, order, covered, note in ROWS
    ]


class _Stub:
    """A stand-in for FindingType.objects serving the seed rows."""

    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_fields):
        return self

    def values(self, *fields):
        return [{field: row[field] for field in fields} for row in self.rows]

    def values_list(self, *fields):
        return [tuple(row[field] for field in fields) for row in self.rows]


def test_the_seed_is_sound():
    assert finding_registry.registry_problems(_rows()) == []


def test_the_seed_has_63_types_5_categories_and_17_groups():
    rows = _rows()
    assert len(rows) == 63
    assert [c for c in dict.fromkeys(r["issue_category"] for r in rows)] == [
        "Inventory",
        "Agents & reporting",
        "Software & security",
        "Patching & support",
        "Data collection",
    ]
    assert len({r["issue_group"] for r in rows}) == 17


def test_the_seed_covers_exactly_the_twelve_symptom_pairs():
    pairs = {(parent, r["name"]) for r in _rows() for parent in r["covered_by"]}
    assert len(pairs) == 12
    for real_fact in ("device_never_patched", "patch_failing_repeatedly", "device_unenrolled"):
        assert real_fact not in {dependent for _p, dependent in pairs}
    assert ("device_missing_from_source", "device_source_record_withdrawn") in pairs
    assert ("patching_stalled", "reboot_pending") in pairs


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda rows: rows[1].update(display_name=rows[0]["display_name"]), "share the name"),
        (lambda rows: rows[0].update(display_name=" "), "no display name"),
        (lambda rows: rows[0].update(issue_group=""), "needs a category and a group"),
        (lambda rows: rows[0].update(covered_by=[rows[0]["name"]]), "cannot cover itself"),
        (lambda rows: rows[0].update(covered_by=["no_such_type"]), "unknown type"),
        (lambda rows: rows[2].update(issue_category="Data collection"), "two categories"),
    ],
)
def test_problems_are_reported(mutate, expected):
    rows = _rows()
    mutate(rows)
    assert any(expected in problem for problem in finding_registry.registry_problems(rows))


def test_a_cycle_is_reported():
    rows = {r["name"]: r for r in _rows()}
    # missing_from_source covers offline in the seed; making offline cover it back is a cycle.
    rows["device_missing_from_source"]["covered_by"] = ["device_offline"]
    problems = finding_registry.registry_problems(list(rows.values()))
    assert any("cover each other" in problem for problem in problems)


def test_taxonomy_is_built_from_the_registry_in_sort_order(monkeypatch):
    monkeypatch.setattr(FindingType, "objects", _Stub(_rows()), raising=False)
    categories, groups = finding_registry.build_taxonomy()
    assert [c["key"] for c in categories] == [
        "inventory",
        "agents_reporting",
        "software_security",
        "patching_support",
        "data_collection",
    ]
    assert len(groups) == 17
    approval = groups["software_approval"]
    assert approval["types"] == {"rare_recent", "whitelist_suggestion"}
    assert approval["category"] == "software_security"
    assert [i["value"] for i in approval["issues"]] == ["rare_recent", "whitelist_suggestion"]
    # Every type is in exactly one group.
    assert sum(len(g["types"]) for g in groups.values()) == 63


def test_one_lookup_gives_the_display_name_and_unknown_types_keep_their_code_name(monkeypatch):
    monkeypatch.setattr(finding_registry, "_load_names", lambda: {r[0]: r[1] for r in ROWS})
    assert finding_registry.finding_type_name("device_offline") == "Computer offline"
    assert finding_registry.finding_type_name("not_a_type") == "not_a_type"
    assert human_labels.humanize_label("reboot_pending") == "Restart required"


def test_no_screen_keeps_its_own_finding_type_name():
    names = {row[0] for row in ROWS}
    assert not names & set(human_labels._LABELS)
    views = (_ROOT / "apps" / "core" / "views.py").read_text(encoding="utf-8")
    assert 'definitions.get(item["type_name"]' not in views
    assert '.get("label"' not in views.split("def _condition_coverage_summary")[1][:3000]
    assert "profile.issue_taxonomy" not in views


def test_group_and_category_moves_swap_neighbours_and_keep_the_order_inside():
    rows = _rows()
    changes = finding_types_admin.renumber_after_move(
        rows, "issue_category", "Agents & reporting", -1
    )
    assert changes
    moved = [
        {**r, "sort_order": changes.get(r["name"], r["sort_order"])} for r in rows
    ]
    assert finding_types_admin.blocks(moved, "issue_category")[:2] == [
        "Agents & reporting",
        "Inventory",
    ]
    # Moving the first block up, or the last down, changes nothing.
    assert finding_types_admin.renumber_after_move(rows, "issue_category", "Inventory", -1) == {}
    assert (
        finding_types_admin.renumber_after_move(rows, "issue_category", "Data collection", 1) == {}
    )
    # A group moves only among its own category's groups.
    group_changes = finding_types_admin.renumber_after_move(
        rows, "issue_group", "Computers offline", -1, "Agents & reporting"
    )
    moved = [{**r, "sort_order": group_changes.get(r["name"], r["sort_order"])} for r in rows]
    agents = [r for r in moved if r["issue_category"] == "Agents & reporting"]
    assert finding_types_admin.blocks(agents, "issue_group") == ["Computers offline", "Required agents"]


def test_page_is_staff_only_and_every_change_is_audited():
    source = (_ROOT / "apps" / "core" / "finding_types_admin.py").read_text(encoding="utf-8")
    assert "if not request.user.is_staff:" in source
    for action in (
        "finding_type.update",
        "finding_type.covers_update",
        "finding_category.rename",
        "finding_group.rename",
        "finding_category.move",
        "finding_group.move",
    ):
        assert f'"{action}"' in source
    assert "finding_registry.registry_problems(rows)" in source
    urls = (_ROOT / "config" / "urls.py").read_text(encoding="utf-8")
    assert 'name="finding_types_config"' in urls
    assert "finding_alert_eligibility" not in urls


def test_migration_enforces_the_registry_in_the_database():
    sql = _MIGRATION.CONSTRAINTS_SQL
    assert "NOT (covered_by ? name)" in sql
    assert "display_name <> ''" in sql
    ingest = (_ROOT.parent / "ingest" / "notifications.py").read_text(encoding="utf-8")
    assert "ft.display_name AS finding_type_display" in ingest
