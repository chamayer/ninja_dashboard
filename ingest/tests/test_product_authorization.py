"""Authorization is not a coverage requirement.

`_load_sanctioned_product_identities` permits a product only when the client
*requires* its platform, and the same rows drive `missing_required_platform`.
So the only way to authorize software was to mandate it. Measured 2026-08-13:
ScreenConnect is required by one requirement profile, the global fallback
requires only LogMeIn / Ninja / SentinelOne, and 70 of 76 clients have no
profile -- so the MSP's own instance on 3,007 devices read as unauthorized,
and silencing it by making it required would have demanded it from the five
clients that do not run it.

`operations.product_authorizations` answers the authorization question on its
own. These tests pin the precedence ladder, because every failure it can have
is silent: the wrong order either suppresses a real finding or accuses
sanctioned software, and neither raises.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

_EMITTER = Path(__file__).resolve().parents[1] / "software_findings.py"
_MIGRATION = (
    Path(__file__).resolve().parents[2] / "sql" / "migrations"
    / "099_product_authorizations.sql"
)
_DJANGO_MIGRATION = (
    Path(__file__).resolve().parents[2] / "operations" / "apps" / "core"
    / "migrations" / "0139_product_authorizations.py"
)

CLIENT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
PRODUCT = "33333333-3333-3333-3333-333333333333"


def _import_emitter():
    """Import the emitter, stubbing `ingest.config` when pydantic is absent.

    `pytest.importorskip` was the obvious choice and the wrong one: pydantic is
    not installed on a bare workstation, so every behavioral test below would
    silently skip and the ladder would go unverified exactly where a mistake is
    invisible. `_permitted` is pure logic that reads no settings, so a stub is
    enough to exercise it honestly. Anything other than a missing pydantic is
    re-raised -- a real import error must still fail.
    """
    try:
        import ingest.software_findings as sf
    except ModuleNotFoundError as exc:
        if exc.name != "pydantic":
            raise
        stub = types.ModuleType("ingest.config")
        stub.settings = types.SimpleNamespace()
        sys.modules.setdefault("ingest.config", stub)
        import ingest.software_findings as sf
    return sf


def _auth(scope, capability, permit=(), deny=()):
    return {scope: {capability: {"permit": set(permit), "deny": set(deny)}}}


def test_client_permit_authorizes_without_requiring_the_platform() -> None:
    """The whole point: permitted without being mandated."""
    sf = _import_emitter()
    auth = _auth(CLIENT, "remote_access", permit=[PRODUCT])
    permitted, basis = sf._permitted(auth, {}, CLIENT, "remote_access", PRODUCT)
    assert permitted is True
    assert basis == "client permit"


def test_global_permit_covers_every_client() -> None:
    sf = _import_emitter()
    auth = _auth(None, "remote_access", permit=[PRODUCT])
    for client in (CLIENT, OTHER):
        permitted, basis = sf._permitted(auth, {}, client, "remote_access", PRODUCT)
        assert permitted is True, client
        assert basis == "global permit"


def test_client_deny_overrides_a_global_permit() -> None:
    """The case a single boolean cannot express: permitted fleet-wide, excluded
    at one client."""
    sf = _import_emitter()
    auth = _auth(None, "remote_access", permit=[PRODUCT])
    auth[CLIENT] = {"remote_access": {"permit": set(), "deny": {PRODUCT}}}

    denied, basis = sf._permitted(auth, {}, CLIENT, "remote_access", PRODUCT)
    assert denied is False
    assert basis == "client deny"

    # Every other client keeps the global permit.
    permitted, _ = sf._permitted(auth, {}, OTHER, "remote_access", PRODUCT)
    assert permitted is True


def test_deny_precedes_permit_within_one_tier() -> None:
    """A contradictory pair must resolve to deny, not to insertion order."""
    sf = _import_emitter()
    auth = _auth(CLIENT, "remote_access", permit=[PRODUCT], deny=[PRODUCT])
    denied, basis = sf._permitted(auth, {}, CLIENT, "remote_access", PRODUCT)
    assert denied is False
    assert basis == "client deny"


def test_global_deny_does_not_override_a_client_permit() -> None:
    """More specific wins: the client tier is consulted first, and a client
    permit is a decision about that client, not an oversight."""
    sf = _import_emitter()
    auth = _auth(None, "remote_access", deny=[PRODUCT])
    auth[CLIENT] = {"remote_access": {"permit": {PRODUCT}, "deny": set()}}
    permitted, basis = sf._permitted(auth, {}, CLIENT, "remote_access", PRODUCT)
    assert permitted is True
    assert basis == "client permit"


def test_required_platform_still_permits_and_ranks_last() -> None:
    """Existing coverage-derived behavior is unchanged."""
    sf = _import_emitter()
    sanctioned = {CLIENT: {"remote_access": {PRODUCT}}}
    permitted, basis = sf._permitted({}, sanctioned, CLIENT, "remote_access", PRODUCT)
    assert permitted is True
    assert basis == "required platform"


def test_any_deny_beats_the_required_platform_mapping() -> None:
    """An explicit deny is an operator decision; a required-platform mapping is
    an inference from coverage policy."""
    sf = _import_emitter()
    sanctioned = {CLIENT: {"remote_access": {PRODUCT}}}
    auth = _auth(None, "remote_access", deny=[PRODUCT])
    denied, basis = sf._permitted(auth, sanctioned, CLIENT, "remote_access", PRODUCT)
    assert denied is False
    assert basis == "global deny"


def test_absent_everywhere_is_not_permitted() -> None:
    sf = _import_emitter()
    permitted, basis = sf._permitted({}, {}, CLIENT, "remote_access", PRODUCT)
    assert permitted is False
    assert "not mapped to a required platform" in basis


def test_authorization_is_capability_scoped() -> None:
    """Permitting a product as remote_access must not permit it as rmm."""
    sf = _import_emitter()
    auth = _auth(None, "remote_access", permit=[PRODUCT])
    permitted, _ = sf._permitted(auth, {}, CLIENT, "rmm", PRODUCT)
    assert permitted is False


def test_loader_excludes_withdrawn_rows() -> None:
    """A withdrawn authorization has no force. Filtering at the loader rather
    than the call site means no caller can forget to."""
    code = _EMITTER.read_text(encoding="utf-8")
    loader = code.split("def _load_authorizations")[1].split("def ")[0]
    assert "withdrawn_at IS NULL" in loader


def test_schema_probe_fails_closed_without_the_table() -> None:
    """Authorization is what suppresses an unauthorized finding, so a missing
    table must read as capability-not-ready rather than leave enforcement
    running with nothing able to permit."""
    code = _EMITTER.read_text(encoding="utf-8")
    probe = code.split("def _capability_schema_ready")[1].split("def ")[0]
    assert "operations.product_authorizations" in probe


def test_polarity_has_no_default_in_either_runner() -> None:
    """Permit and deny are opposite decisions. A default would let an
    incomplete write silently become a permit."""
    raw = _MIGRATION.read_text(encoding="utf-8")
    polarity = re.search(r"polarity\s+boolean[^,]*", raw)
    assert polarity is not None
    assert "DEFAULT" not in polarity.group(0).upper()
    assert "NOT NULL" in polarity.group(0).upper()

    django = _DJANGO_MIGRATION.read_text(encoding="utf-8")
    field = re.search(r'\("polarity", models\.BooleanField\(([^)]*)\)\)', django)
    assert field is not None
    assert "default" not in field.group(1)


def test_withdrawal_records_a_reason() -> None:
    """Nothing leaves the table without a time and a cause."""
    raw = _MIGRATION.read_text(encoding="utf-8")
    assert "ck_product_authorizations_withdrawal" in raw
    assert "withdrawn_reason <> ''" in raw


def test_delete_is_revoked() -> None:
    """Withdrawal is the retirement path, so an authorization once in force can
    always be shown to have been."""
    raw = _MIGRATION.read_text(encoding="utf-8")
    revoke = re.search(r"REVOKE DELETE, TRUNCATE ON operations\.product_authorizations[^;]*;", raw)
    assert revoke is not None
    for role in ("operations_app", "ninja_ingest"):
        assert role in revoke.group(0), role


def test_product_authorization_parity() -> None:
    """The two migration runners must describe the same table.

    Migration 0131 states outright that column parity across the raw SQL and
    Django definitions is load-bearing and that nothing enforces it. This is
    that enforcement: the raw DDL owns the table, Django declares state only,
    and a column added to one and not the other is a drift no runtime check
    would surface.
    """
    raw = _MIGRATION.read_text(encoding="utf-8")
    body = raw.split("CREATE TABLE IF NOT EXISTS operations.product_authorizations (")[1]
    body = body.split("\n);")[0]
    # Constraints are declared after every column, and the multi-line CHECK
    # bodies are not column definitions -- cut there rather than trying to skip
    # their continuation lines.
    body = body.split("CONSTRAINT")[0]
    sql_columns = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        sql_columns.add(line.split()[0])

    django = _DJANGO_MIGRATION.read_text(encoding="utf-8")
    # Relation fields are wrapped across lines, so the name and `models.` are
    # not adjacent.
    django_fields = set(re.findall(r'\(\s*"([a-z_]+)",\s*models\.', django))
    # Django names a relation `client`; the column is `client_id`.
    normalized = {
        f"{name}_id" if name in {"tenant", "client", "authorized_by"} else name
        for name in django_fields
    }
    assert normalized == sql_columns, (
        f"only in SQL: {sorted(sql_columns - normalized)}; "
        f"only in Django: {sorted(normalized - sql_columns)}"
    )


def test_required_loader_is_untouched_by_authorization() -> None:
    """Coverage semantics must not shift: `_load_sanctioned_product_identities`
    remains the required-platform source and gains no authorization logic."""
    code = _EMITTER.read_text(encoding="utf-8")
    loader = code.split("def _load_sanctioned_product_identities")[1].split("\ndef ")[0]
    assert "product_authorizations" not in loader
    assert "required_platforms" in loader
