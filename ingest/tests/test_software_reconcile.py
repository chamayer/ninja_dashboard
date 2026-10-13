from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest import software_reconcile as sr
from shared import software_settings
from shared.conditions.policy import parse_profile

_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
PROFILE = parse_profile(
    json.loads((_ROOT / "shared" / "conditions" / "profile.json").read_text(encoding="utf-8"))
)

TYPES = {
    name: sr.FindingType(i, name, scope, suppressed, concern, severity, True)
    for i, (name, scope, suppressed, concern, severity) in enumerate(
        [
            ("suspicious_name", "software_product", True, True, "medium"),
            ("install_path_suspicious", "software_installation", False, True, "medium"),
            ("known_malicious_hint", "software_product", False, True, "low"),
            ("rare_recent", "software_product", True, True, "medium"),
            ("whitelist_suggestion", "software_product", True, False, "low"),
            ("vulnerable_software", "software_version", False, False, "high"),
            ("eol_runtime", "software_version", False, False, "high"),
            ("unauthorized_remote_access", "device", True, True, "high"),
            ("rejected_software_installed", "software_product", False, True, "high"),
        ],
        start=1,
    )
}
SUGGESTIONS = [
    (10, "threat_hit", True, "investigate"),
    (20, "install_path", True, "investigate"),
    (30, "suspicious_name", True, "investigate"),
    (40, "unauthorized_capability", True, "review_capability"),
    (50, "junk_publisher", True, "investigate"),
    (60, "established_publisher", False, "approve_publisher"),
    (70, "prevalent", False, "approve_title"),
    (80, "fallback", False, "none"),
]


def _title(name, devices, *, publisher="Acme Corp", clients=1, first_seen=None,
           undecided=True, has_unapproved=True, publisher_only=False, product="p-" ):
    return {
        "title_key": name.lower(), "canonical_name": name, "publisher": publisher,
        "devices": devices, "clients": clients,
        "first_seen": first_seen or NOW - timedelta(days=100),
        "product_uuid": f"{product}{name.lower()}", "undecided": undecided,
        "has_unapproved": has_unapproved, "has_publisher_only_approval": publisher_only,
    }


def _ctx(titles=(), versions=(), *, vulnerable=None, hits=None, paths=(), rules=None,
         cfg=None):
    return sr.Context(
        tenant_id=1, now=NOW, cfg={**software_settings.effective({}), **(cfg or {})},
        types=TYPES,
        rules=sr.compile_rules(rules or [
            ("suspicious_name", r"crack|keygen", True),
            ("eol_runtime", r"^java 6", True),
            ("junk_publisher", r"^\s*$", True),
            ("install_path_suspicious", r"\\temp\\", True),
        ]),
        suggestion_rules=SUGGESTIONS,
        titles={t["title_key"]: t for t in titles},
        versions=list(versions), vulnerable=vulnerable or {}, threat_hits=hits or {},
        path_installs=list(paths), capability_installs=[], capabilities={},
        authorizations={}, sanctioned={},
    )


def _desired(ctx, monkeypatch=None):
    report = sr.RunReport()
    return sr.compute_desired(ctx, report), report


def test_condition_keys_are_identical_to_the_previous_classifier():
    from ingest.software_findings import _condition_key

    assert sr.condition_key(1, None, None, 7, "Zoom") == _condition_key(1, None, None, "7", "Zoom")
    assert sr.condition_key(1, "c", "d", 7, "Zoom@v") == _condition_key(1, "c", "d", "7", "Zoom@v")


def test_undecided_titles_split_at_the_rare_limit_with_no_gap():
    desired, _ = _desired(_ctx([_title("A", 1), _title("B", 2), _title("C", 3)]))
    rare = {d.details["canonical_name"] for d in desired["rare_recent"]}
    non_approved = {d.details["canonical_name"] for d in desired["whitelist_suggestion"]}
    assert rare == {"A", "B"} and non_approved == {"C"}


def test_recency_is_a_severity_signal_not_a_condition():
    old = _title("Old", 1, first_seen=NOW - timedelta(days=400))
    new = _title("New", 1, first_seen=NOW - timedelta(days=1))
    desired, _ = _desired(_ctx([old, new]))
    severity = {d.details["canonical_name"]: d.severity for d in desired["rare_recent"]}
    assert severity == {"Old": "low", "New": "medium"}  # old rare software is still a finding


def test_any_decision_closes_the_review_prompt():
    decided = _title("Decided", 5, undecided=False)
    desired, _ = _desired(_ctx([decided]))
    assert not desired.get("whitelist_suggestion") and not desired.get("rare_recent")


def test_rejected_software_stays_a_finding_while_installed():
    rejected = {**_title("Banned", 4, undecided=False), "rejected_devices": 3,
                "rejected_clients": 2}
    desired, _ = _desired(_ctx([rejected, _title("Fine", 4, undecided=False)]))
    [finding] = desired["rejected_software_installed"]
    assert finding.details["canonical_name"] == "Banned"
    assert finding.details["rejected_device_count"] == 3
    assert finding.severity == "high"
    assert finding.condition_key == sr.condition_key(
        1, None, None, TYPES["rejected_software_installed"].id, "Banned"
    )


def test_rejected_software_switch_stops_the_type():
    rejected = {**_title("Banned", 4, undecided=False), "rejected_devices": 1}
    desired, report = _desired(_ctx([rejected], cfg={"rejected_installed_enabled": False}))
    assert not desired.get("rejected_software_installed")
    assert "rejected_software_installed" in report.disabled


def test_title_approval_silences_a_suspicious_name():
    approved = _title("SuperCrack", 5, undecided=False, has_unapproved=False)
    desired, _ = _desired(_ctx([approved]))
    assert not desired.get("suspicious_name")


def test_publisher_approval_silences_only_without_another_concern():
    title = _title("SuperCrack", 5, undecided=False, has_unapproved=False, publisher_only=True)
    desired, _ = _desired(_ctx([title]))
    assert not desired.get("suspicious_name")
    path = ("inst-1", "dev-1", "cli-1", "supercrack", "SuperCrack", "Acme Corp",
            r"c:\temp\x", None, "approve_publisher")
    desired, _ = _desired(_ctx([title], paths=[path]))
    assert [d.details["canonical_name"] for d in desired["suspicious_name"]] == ["SuperCrack"]


def test_rare_survives_publisher_approval_when_another_concern_exists():
    title = _title("SuperCrack", 1, undecided=False, has_unapproved=False, publisher_only=True)
    desired, _ = _desired(_ctx([title]))
    assert [d.details["canonical_name"] for d in desired["rare_recent"]] == ["SuperCrack"]


def test_vulnerable_versions_ignore_approval_and_keep_version_keys():
    title = _title("Reader", 9, undecided=False, has_unapproved=False)
    vuln = {"reader": {"kev": ["CVE-1"], "high": [], "worst_cvss": 9.8, "max_epss": 0.9}}
    desired, _ = _desired(_ctx([title], [("reader", "ver-1", "1.0", 9)], vulnerable=vuln))
    (row,) = desired["vulnerable_software"]
    assert row.severity == "critical" and row.subject_type == "software_version"
    assert row.condition_key == sr.condition_key(1, None, None, TYPES["vulnerable_software"].id,
                                                 "Reader@ver-1")


def test_per_type_switch_stops_a_type_and_reports_it():
    desired, report = _desired(_ctx([_title("A", 1)], cfg={"rare_enabled": False}))
    assert not desired.get("rare_recent") and "rare_recent" in report.disabled


def test_unlinked_titles_are_counted_not_dropped_silently():
    title = _title("Loose", 1)
    title["product_uuid"] = None
    _, report = _desired(_ctx([title]))
    assert report.unlinked["rare_recent"] == 1


def test_suggestions_put_adverse_rules_first():
    assert sr.suggestion_for(SUGGESTIONS, {"prevalent", "threat_hit"}) == "investigate"
    assert sr.suggestion_for(SUGGESTIONS, {"prevalent"}) == "approve_title"
    assert sr.suggestion_for(SUGGESTIONS, set()) == "none"


def test_junk_publisher_drives_an_investigate_suggestion():
    desired, _ = _desired(_ctx([_title("Thing", 5, publisher="")]))
    (row,) = desired["whitelist_suggestion"]
    assert row.details["suggestion"] == "investigate"
    assert "junk_publisher" in row.details["signals"]


def _finding(type_name, subject_type, subject_id, *, status="open", snoozed=None, device=None):
    ft = TYPES[type_name]
    return (f"f-{type_name}-{subject_id}", ft.id, type_name, "key", status, snoozed,
            subject_type, subject_id, device)


def test_title_findings_have_one_subject_participant_and_need_a_ready_device():
    findings = [_finding("vulnerable_software", "software_version",
                         "00000000-0000-0000-0000-000000000001")]
    participants, rows = sr.assessment_rows(
        tenant_id=1, now=NOW, profile=PROFILE, findings=findings,
        ready_exposure={}, readiness={},
    )
    assert [p[3] for p in participants] == ["software_version"]
    aggregate = json.loads(rows[0][10])
    assert rows[0][3] == "condition" and aggregate["may_execute"] is False
    assert "exposure:no_live_install" in aggregate["reasons"]
    _, rows = sr.assessment_rows(
        tenant_id=1, now=NOW, profile=PROFILE, findings=findings,
        ready_exposure={findings[0][0]: (True, True, 3, 5)}, readiness={},
    )
    assert json.loads(rows[0][10])["may_execute"] is True
    assert len(rows) == 2  # aggregate + subject; no per-device rows (D1)


def test_device_findings_take_readiness_and_operator_handling():
    device = "00000000-0000-0000-0000-0000000000aa"
    findings = [_finding("unauthorized_remote_access", "device", device,
                         status="open", snoozed=NOW + timedelta(days=1))]
    readiness = {(device, TYPES["unauthorized_remote_access"].id):
                 ("eligible", True, True, [], [])}
    _, rows = sr.assessment_rows(
        tenant_id=1, now=NOW, profile=PROFILE, findings=findings,
        ready_exposure={}, readiness=readiness,
    )
    responses = [json.loads(row[10]) for row in rows]
    assert {r["disposition"] for r in responses} == {"suppressed"}
    assert all(r["may_notify"] is False for r in responses)


class _FakeCursor:
    def __init__(self, counts):
        self.statements: list[str] = []
        self.rowcount = 0
        self._counts = counts

    def execute(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))

    def fetchone(self):
        return self._counts

    @contextmanager
    def copy(self, _sql):
        class _Copy:
            def set_types(self, _types):
                pass

            def write_row(self, _row):
                pass

        yield _Copy()


@pytest.mark.parametrize(("counts", "allow", "closes"), [
    ((60, 100), False, False),
    ((60, 100), True, True),
    ((10, 100), False, True),
    ((15, 15), False, True),   # below the minimum population the limit does not apply
])
def test_close_limit_holds_large_resolutions(counts, allow, closes):
    ctx = _ctx(cfg={"reconcile_allow_large_close": allow})
    cur = _FakeCursor(counts)
    report = sr.RunReport()
    sr.reconcile_type(cur, ctx, TYPES["whitelist_suggestion"], [], report)
    final_close = any("NOT EXISTS ( SELECT 1 FROM software_desired desired" in s
                      and s.startswith("UPDATE operations.findings") for s in cur.statements)
    assert final_close is closes
    assert ("whitelist_suggestion" in report.held_by_limit) is not closes


def test_jobs_run_the_reconcile_without_device_batches():
    source = (_ROOT / "ingest" / "operator_job_queue.py").read_text(encoding="utf-8")
    assert 'if job_key in ("software-classify-only", "software-classify-full"):' in source
    assert 'return _software_reconcile(progress, whole_fleet=job_key == "software-classify-full")' in source
    assert "incremental classifier continuation" not in source
    registry = (_ROOT / "shared" / "jobs_registry.py").read_text(encoding="utf-8")
    assert registry.count('"ingest.software_reconcile.run",') == 2


def test_exposure_read_model_is_staged_and_uses_readiness():
    sql = (_ROOT / "sql" / "migrations" / "114_software_exposure_from_readiness.sql").read_text(
        encoding="utf-8")
    assert "DROP MATERIALIZED VIEW IF EXISTS operations.device_software_exposure_current CASCADE" in sql
    assert sql.count("AS MATERIALIZED (") == 6
    assert "JOIN operations.software_device_readiness readiness" in sql
    assert "aggregate.participant_kind = 'condition'" in sql
    assert "participant_kind = 'device'" not in sql
    assert "FROM (SELECT DISTINCT tenant_id, device_id, canonical_name FROM candidates) pair" in sql
    assert "CREATE OR REPLACE VIEW operations.v_device_software_exposure" in sql
    assert "finding_type.suppressed_by_approval" in sql


def test_a_findings_run_describes_itself_with_policy_labels():
    report = sr.RunReport()
    report.labels = {"rejected_software_installed": "Rejected software is installed"}
    report.opened["rejected_software_installed"] = 41
    report.resolved["rare_recent"] = 3
    report.refreshed["vulnerable_software"] = 400
    text = report.describe()
    assert text.startswith("Software findings (whole fleet): 41 opened, 3 resolved, 400 still current.")
    report.scope_titles = 12
    assert report.describe().startswith("Software findings (12 changed titles):")
    assert "Rejected software is installed: +41 / -0" in text
    assert "rare recent: +0 / -3" in text
    assert report.as_result()["summary"] == report.describe()


# ── Changed-only runs ─────────────────────────────────────────────────


def test_a_run_without_named_titles_covers_the_whole_fleet():
    assert sr.scope_from_targets([]) is None
    assert sr.scope_from_targets([("1", "name:a", "a", None), ("2", "all", "*", None)]) is None


def test_named_titles_and_matched_versions_form_the_scope():
    targets = [("1", "name:zoom", "zoom", None), ("2", "version:9", "", 9)]
    assert sr.scope_from_targets(targets, ["7-zip"]) == ["7-zip", "zoom"]


def test_scoped_queries_filter_by_title_and_whole_fleet_queries_do_not():
    assert "ANY(%(titles)s)" in sr.scoped(sr.TITLE_FACTS_SQL, ["a"])
    assert "lower(match.canonical_name) = ANY(%(titles)s)" in sr.scoped(sr.VULNERABLE_SQL, ["a"])
    for sql in (sr.TITLE_FACTS_SQL, sr.VERSION_FACTS_SQL, sr.VULNERABLE_SQL,
                sr.PATH_INSTALLS_SQL, sr.CAPABILITY_INSTALLS_SQL):
        assert "/*" in sql
        assert "titles" not in sr.scoped(sql, None)


def test_a_scoped_reconcile_never_resolves_findings_of_other_titles():
    source = (_ROOT / "ingest" / "software_reconcile.py").read_text(encoding="utf-8")
    body = source[source.index("def reconcile_type("):source.index("# ── Assessments")]
    guard = "lower(finding.finding_details->>'canonical_name') = ANY(%(titles)s::text[])"
    # Regrain, close-limit count and resolution all carry the title guard.
    assert body.count(guard) == 3
    assert sr.ACTIVE_FINDINGS_SQL.count(guard) == 1
    assert sr.READY_EXPOSURE_SQL.count(guard) == 1


def test_only_title_naming_producers_skip_the_whole_fleet_request():
    from ingest import operator_job_queue

    assert operator_job_queue._software_title_scoped_producers() == {
        "software-queue-drain", "software-enqueue-orgs", "intel-matcher",
    }
