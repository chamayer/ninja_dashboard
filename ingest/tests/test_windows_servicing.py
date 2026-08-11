from contextlib import contextmanager
from datetime import date

from ingest.intel.windows_servicing import (
    Release,
    Rule,
    _extract_build,
    classify_windows,
    rollout_summary,
)


def _release(
    product: str,
    cycle: str,
    build: str,
    *,
    eol: date | None,
    eoas: date | None = None,
    eoes: date | None = None,
) -> Release:
    return Release(
        product,
        cycle,
        cycle,
        build,
        eoas,
        None,
        eol,
        bool(eol and eol <= date(2026, 8, 11)),
        eoes,
        None,
        True,
        "lts" in cycle,
    )


def _rules() -> list[Rule]:
    return [
        Rule(
            "product.windows-server",
            "product",
            10,
            "windows-server",
            r"(?i)\b(?:windows|hyper-v)\s+server\b",
            None,
        ),
        Rule(
            "product.windows-client",
            "product",
            20,
            "windows",
            r"(?i)\bwindows\b",
            None,
        ),
        Rule(
            "edition.iot-lts",
            "edition",
            10,
            "windows",
            r"(?i)\b(?:windows\s+)?iot\b",
            r"-iot-lts$",
        ),
        Rule(
            "edition.lts",
            "edition",
            20,
            "windows",
            r"(?i)\b(?:ltsc|ltsb)\b",
            r"(?<!-iot)-lts$",
        ),
        Rule(
            "edition.enterprise",
            "edition",
            30,
            "windows",
            r"(?i)\b(?:enterprise|education)\b",
            r"-e$",
        ),
        Rule(
            "edition.workstation",
            "edition",
            40,
            "windows",
            r"(?i)\b(?:home|pro(?:fessional)?|workstation)\b",
            r"-w$",
        ),
    ]


def test_extract_build_accepts_full_and_base_versions():
    assert _extract_build("10.0.22631") == 22631
    assert _extract_build("6.3.9600.20520") == 9600
    assert _extract_build("19045.4046") == 19045
    assert _extract_build(9600) == 9600
    assert _extract_build("22H2") is None


def test_windows_10_eol_keeps_esu_availability_separate_from_entitlement():
    result = classify_windows(
        "Microsoft Windows 10 Pro",
        "10.0.19045",
        "22H2",
        [
            _release(
                "windows",
                "10-22h2",
                "10.0.19045",
                eol=date(2025, 10, 14),
                eoes=date(2028, 10, 10),
            )
        ],
        _rules(),
        today=date(2026, 8, 11),
    )

    assert result is not None
    assert result.support_state == "eol_esu_available"
    assert result.extended_security_available is True
    assert result.release and result.release.cycle == "10-22h2"


def test_shared_windows_11_build_uses_edition_rule():
    releases = [
        _release(
            "windows", "11-23h2-w", "10.0.22631", eol=date(2025, 11, 11)
        ),
        _release(
            "windows", "11-23h2-e", "10.0.22631", eol=date(2026, 11, 10)
        ),
    ]

    pro = classify_windows(
        "Microsoft Windows 11 Pro",
        "22631",
        "23H2",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )
    enterprise = classify_windows(
        "Microsoft Windows 11 Enterprise",
        "22631",
        "23H2",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )

    assert pro and pro.release and pro.release.cycle == "11-23h2-w"
    assert pro.support_state == "eol"
    assert enterprise and enterprise.release
    assert enterprise.release.cycle == "11-23h2-e"
    assert enterprise.support_state == "approaching_eol"


def test_unqualified_shared_build_is_unknown_instead_of_guessed():
    releases = [
        _release("windows", "11-23h2-w", "22631", eol=date(2025, 11, 11)),
        _release("windows", "11-23h2-e", "22631", eol=date(2026, 11, 10)),
    ]
    result = classify_windows(
        "Microsoft Windows 11",
        "22631",
        "23H2",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )

    assert result is not None
    assert result.support_state == "unknown"
    assert "multiple cycles" in result.reason


def test_lts_and_iot_lts_shared_builds_do_not_collapse_together():
    releases = [
        _release("windows", "11-24h2-lts", "26100", eol=date(2029, 10, 9)),
        _release(
            "windows", "11-24h2-iot-lts", "26100", eol=date(2034, 10, 10)
        ),
    ]

    lts = classify_windows(
        "Microsoft Windows 11 Enterprise LTSC 2024",
        "26100",
        "24H2",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )
    iot = classify_windows(
        "Microsoft Windows 11 IoT Enterprise LTSC 2024",
        "26100",
        "24H2",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )

    assert lts and lts.release and lts.release.cycle == "11-24h2-lts"
    assert iot and iot.release and iot.release.cycle == "11-24h2-iot-lts"


def test_server_title_year_beats_conflicting_release_id_token():
    releases = [
        _release("windows-server", "2019", "10.0.17763", eol=date(2029, 1, 9)),
        _release(
            "windows-server", "1809-sac", "10.0.17763", eol=date(2020, 11, 10)
        ),
    ]
    result = classify_windows(
        "Microsoft Windows Server 2019 Standard",
        "17763",
        "1809",
        releases,
        _rules(),
        today=date(2026, 8, 11),
    )

    assert result and result.release and result.release.cycle == "2019"
    assert result.support_state == "supported"


def test_non_windows_os_has_no_windows_servicing_row():
    assert classify_windows("Ubuntu 24.04", "6.8.0", "24.04", [], _rules()) is None


class _SummaryCursor:
    def __init__(self, *, present: bool, states=(), invalid=(0, 0, 0)):
        self.present = present
        self.states = states
        self.invalid = invalid
        self.query = ""

    def execute(self, query, _params=None):
        self.query = query

    def fetchone(self):
        if "to_regclass" in self.query:
            return (self.present,)
        return self.invalid

    def fetchall(self):
        return self.states


def test_rollout_summary_is_safe_before_the_schema_migration(monkeypatch):
    cursor = _SummaryCursor(present=False)

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr("ingest.intel.windows_servicing.db.transaction", transaction)

    assert rollout_summary(1) == {
        "states": {},
        "missing_cycle": 0,
        "missing_security_end": 0,
        "unexplained_unknown": 0,
        "invalid_rows": 0,
        "status": "migration_pending",
    }


def test_rollout_summary_counts_invalid_projected_rows(monkeypatch):
    cursor = _SummaryCursor(
        present=True,
        states=(("eol", 5), ("supported", 20), ("unknown", 2)),
        invalid=(1, 2, 3),
    )

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr("ingest.intel.windows_servicing.db.transaction", transaction)

    assert rollout_summary(1) == {
        "states": {"eol": 5, "supported": 20, "unknown": 2},
        "missing_cycle": 1,
        "missing_security_end": 2,
        "unexplained_unknown": 3,
        "invalid_rows": 6,
    }
