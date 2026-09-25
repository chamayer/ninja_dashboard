from pathlib import Path


def test_client_name_drift_compares_reported_names_exactly():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    section = source[source.index("def _check_name_drift"):source.index("def _resolve_unseen_client_name_conflicts")]

    assert "count(DISTINCT observed_name) AS distinct_name_count" in section
    assert "COALESCE(NULLIF(observed_norm" not in section
