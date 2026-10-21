from pathlib import Path


def test_user_exposure_bounds_html_rows_but_retains_complete_csv_export():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    start = source.index("def software_user_risk")
    end = source.index("# ─────────────────────────────────────────────────────────────────────\n# Jobs", start)
    view = source[start:end]

    assert "is_csv = wants_csv(request)" in view
    assert "if is_csv:" in view
    assert "ranked_users AS MATERIALIZED" in view
    assert "page_rank_start" in view
    assert "ranked.user_rank >" in view
    assert "ROW_NUMBER() OVER" in view
    assert "AND ranked.user_rank <= {page_rank_start + page_size}" in view
    assert '"users": users,' in view
    assert '"users": users[:500]' not in view
