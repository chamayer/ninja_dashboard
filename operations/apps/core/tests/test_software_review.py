from __future__ import annotations

from pathlib import Path

from apps.core import software_review as review

_VIEWS = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")


def _row(fid, type_name, title, publisher, *, devices=5, signals=(), suggestion="approve_title",
         severity="low"):
    details = {
        "canonical_name": title, "publisher": publisher, "fleet_device_count": devices,
        "client_count": 1, "signals": list(signals), "suggestion": suggestion,
    }
    scope = "device" if type_name == "rare_recent" else "global"
    return (fid, type_name, severity, details, None, scope)


def test_titles_keep_their_own_rows_inside_publisher_groups():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "Acme Paint", "Acme"),
        _row("2", "rare_recent", "Acme Tool", "Acme", devices=1),
        _row("3", "whitelist_suggestion", "Solo", "Other"),
    ])
    assert [g["publisher"] for g in groups] == ["Acme", "Other"]  # most titles first
    assert {t["title"] for t in groups[0]["titles"]} == {"Acme Paint", "Acme Tool"}
    assert {t["type_label"] for t in groups[0]["titles"]} == {"Non-approved", "Rare"}


def test_a_concern_on_any_title_asks_for_title_review_before_the_publisher():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "Clean", "Acme", suggestion="approve_publisher"),
        _row("2", "whitelist_suggestion", "Shady", "Acme", signals=["install_path"],
             suggestion="investigate"),
    ])
    assert groups[0]["suggestion"] == "review_titles"
    assert groups[0]["suggestion_label"] == "Review titles first (1 with concerns)"


def test_established_publisher_without_concerns_suggests_approving_it():
    groups = review.build_groups([
        _row("1", "whitelist_suggestion", "A", "Acme", suggestion="approve_publisher"),
        _row("2", "whitelist_suggestion", "B", "Acme", suggestion="approve_title"),
    ])
    assert groups[0]["suggestion"] == "approve_publisher"


def test_titles_without_a_publisher_cannot_be_approved_by_publisher():
    groups = review.build_groups([_row("1", "rare_recent", "Thing", "", devices=1)])
    assert groups[0]["suggestion"] == "decide_titles"


def test_filters_narrow_by_type_suggestion_and_text():
    rows = [
        _row("1", "whitelist_suggestion", "Alpha", "Acme"),
        _row("2", "rare_recent", "Beta", "Acme", devices=1, suggestion="investigate"),
    ]
    assert [t["title"] for g in review.build_groups(rows, kind="rare_recent") for t in g["titles"]] == ["Beta"]
    assert [t["title"] for g in review.build_groups(rows, suggestion="approve_title") for t in g["titles"]] == ["Alpha"]
    assert [t["title"] for g in review.build_groups(rows, query="alp") for t in g["titles"]] == ["Alpha"]


def test_pages_hold_whole_publisher_groups():
    items, page, pages = review.paginate(list(range(85)), 3, per_page=40)
    assert (items, page, pages) == ([80, 81, 82, 83, 84], 3, 3)
    assert review.paginate([], 5)[1:] == (1, 1)


class _Cursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 2

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def test_a_title_decision_closes_its_prompts_and_a_publisher_decision_spares_concerns():
    cur = _Cursor()
    closed = review.resolve_decided_prompts(
        cur, tenant_id=1, canonical_names=["Acme Paint"], publishers=["Acme"],
        decision="approve_publisher", actor="admin", decided_at="2026-10-13T00:00:00Z",
    )
    assert closed == 4
    title_sql, title_params = cur.calls[0]
    assert "finding_type.name IN ('whitelist_suggestion', 'rare_recent')" in title_sql
    assert title_params["names"] == ["acme paint"]
    publisher_sql, publisher_params = cur.calls[1]
    assert "finding_type.name = 'rare_recent' AND COALESCE(jsonb_array_length(" in publisher_sql
    assert publisher_params["pubs"] == ["acme"]
    assert '"reason": "decision_recorded"' in publisher_params["resolution"]


def test_queue_and_decisions_use_the_review_module():
    body = _VIEWS[_VIEWS.index("def software_decisions_queue(") :]
    body = body[: body.index("\ndef ", 1)]
    assert "software_review.PROMPTS_SQL" in body
    assert "software_review.build_groups(" in body
    assert _VIEWS.count("software_review.resolve_decided_prompts(") == 2


def test_decision_writes_refresh_risk_view_only_after_commit():
    """A best-effort refresh must not abort the durable decision transaction."""
    bulk = _VIEWS[_VIEWS.index("def software_decision_bulk(") :]
    bulk = bulk[: bulk.index("\ndef ", 1)]
    create = _VIEWS[_VIEWS.index("def software_decision_create(") :]
    create = create[: create.index("\ndef ", 1)]

    for body in (bulk, create):
        assert "transaction.on_commit(_refresh_software_risk_matview)" in body
        assert "\n    _refresh_software_risk_matview()" not in body


def test_rare_limit_preview_splits_every_title_into_exactly_one_type():
    distribution = {1: 6000, 2: 3883, 3: 1800, 5: 1200, 10: 300}
    now = review.rare_limit_preview(distribution, 2, 2)
    assert (now["rare"], now["non_approved"], now["moves"]) == (9883, 3300, 0)
    raised = review.rare_limit_preview(distribution, 3, 2)
    assert (raised["rare"], raised["non_approved"]) == (11683, 1500)
    assert raised["moves"] == 1800 and raised["rare"] + raised["non_approved"] == raised["total"]
    lowered = review.rare_limit_preview(distribution, 1, 2)
    assert lowered["moves"] == 3883


def test_classifier_settings_page_embeds_the_preview():
    template = (Path(__file__).resolve().parents[3] / "templates" / "classifier_config.html").read_text(
        encoding="utf-8")
    assert 'id="rare-preview"' in template and 'json_script:"rare-distribution"' in template
    assert "Nothing changes until you save." in template
    assert "rare_distribution" in _VIEWS and "DEVICE_COUNTS_SQL" in _VIEWS
