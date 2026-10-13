from pathlib import Path


def test_tech_checklist_bounds_html_devices_but_retains_complete_csv_export():
    source = Path("apps/core/views.py").read_text(encoding="utf-8")
    start = source.index("def software_tech_checklist")
    end = source.index("def devices_page", start)
    view = source[start:end]

    assert "is_csv = wants_csv(request)" in view
    assert "deduplicated_items AS MATERIALIZED" in view
    assert "eligible_devices AS MATERIALIZED" in view
    assert "ranked_devices AS MATERIALIZED" in view
    assert "WHERE ranked.device_rank <= 500" in view
    assert '"devices": devices,' in view
    assert '"devices": devices[:500]' not in view
