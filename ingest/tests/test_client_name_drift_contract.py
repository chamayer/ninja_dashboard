from pathlib import Path


def test_client_name_drift_compares_reported_names_exactly():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    section = source[source.index("def _check_name_drift"):source.index("def _resolve_unseen_client_name_conflicts")]

    assert "count(DISTINCT observed_name) AS distinct_name_count" in section
    assert "COALESCE(NULLIF(observed_norm" not in section
    assert 'severity="critical"' in section
    assert '"low" if mapping_state == "automatic" else "medium"' not in section


def test_client_mapping_findings_refresh_current_evaluation_fields():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    emit = source[source.index("def _emit_finding"):source.index("def _resolve_finding")]
    unnamed = source[
        source.index("def _emit_unnamed_source_group_finding") : source.index("def _emit_finding")
    ]

    assert "subject_ref      = EXCLUDED.subject_ref" in emit
    assert "severity         = EXCLUDED.severity" in emit
    assert "severity = EXCLUDED.severity" in unnamed


def test_client_name_drift_closes_entity_findings_with_closed_at():
    source = (Path(__file__).parents[1] / "identity" / "client_resolver.py").read_text()
    resolve_one = source[source.index("def _resolve_entity_finding"):source.index("def _check_name_drift")]
    resolve_unseen = source[source.index("def _resolve_unseen_client_name_conflicts"):source.index("def _check_mapping_topology")]

    assert "closed_at = NOW()" in resolve_one
    assert "closed_at = NOW()" in resolve_unseen
    assert "resolved_at" not in resolve_one
    assert "resolved_at" not in resolve_unseen
