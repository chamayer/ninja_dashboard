"""Client domains: learned from computers, edited by operators (ADR-0042)."""

from __future__ import annotations

import importlib
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.template.loader import get_template

from apps.core import client_domains

migration = importlib.import_module("apps.core.migrations.0343_client_domains")
_ROOT = Path(__file__).resolve().parents[3]
CLIENT = SimpleNamespace(id=uuid.UUID(int=1), entity_id=uuid.UUID(int=1), entity=object())


def _learned(rows, config=None):
    cursor = mock.MagicMock()
    cursor.fetchall.return_value = rows
    settings = {**client_domains.DEFAULTS, **(config or {})}
    settings["ignored"] = set(settings["ignored"])
    with (
        mock.patch.object(client_domains, "settings", return_value=settings),
        mock.patch.object(client_domains.connection, "cursor", return_value=nullcontext(cursor)),
        mock.patch.object(client_domains.transaction, "atomic", return_value=nullcontext()),
    ):
        return client_domains.learned([str(CLIENT.id)])


def test_a_domain_is_learned_from_enough_computers_and_never_from_ignored_values():
    learned = _learned(
        [
            (str(CLIENT.id), "starfire.local", 12),
            (str(CLIENT.id), "workgroup", 30),
            (str(CLIENT.id), "contractor.local", 1),
        ]
    )
    assert learned == {str(CLIENT.id): {"starfire.local": 12}}
    assert _learned([(str(CLIENT.id), "contractor.local", 1)], {"min_computers": 1}) == {
        str(CLIENT.id): {"contractor.local": 1}
    }


def test_operator_edits_join_and_override_what_is_learned():
    with (
        mock.patch.object(
            client_domains, "learned", return_value={str(CLIENT.id): {"a.local": 3, "b.local": 2}}
        ),
        mock.patch.object(client_domains, "definition", return_value=object()),
        mock.patch.object(
            client_domains,
            "_decided",
            return_value={str(CLIENT.id): {"b.local": "remove", "c.com": "add"}},
        ),
    ):
        rows = client_domains.domains_for([CLIENT])[str(CLIENT.id)]
    assert [(r["domain"], r["computers"], r["added"], r["removed"]) for r in rows] == [
        ("a.local", 3, False, False),
        ("b.local", 2, False, True),
        ("c.com", 0, True, False),
    ]


def test_an_edit_carries_every_earlier_edit_and_restoring_the_last_one_ends_the_decision():
    with (
        mock.patch.object(client_domains, "definition", return_value=object()),
        mock.patch.object(
            client_domains, "_decided", return_value={str(CLIENT.id): {"b.local": "remove"}}
        ),
        mock.patch.object(client_domains, "set_attribute_decision") as decide,
    ):
        client_domains.edit(
            actor=object(), client=CLIENT, domain=" C.COM. ", action="add", reason="r"
        )
    members = decide.call_args.kwargs["members"]
    assert [(m.value, m.action) for m in members] == [("b.local", "remove"), ("c.com", "add")]
    with (
        mock.patch.object(client_domains, "definition", return_value=object()),
        mock.patch.object(
            client_domains, "_decided", return_value={str(CLIENT.id): {"b.local": "remove"}}
        ),
        mock.patch.object(client_domains.EntityAttributeDecisionCurrent, "objects") as decisions,
        mock.patch.object(client_domains, "deactivate_attribute_decision") as end,
    ):
        decisions.filter.return_value.exists.return_value = True
        client_domains.edit(
            actor=object(), client=CLIENT, domain="b.local", action="restore", reason="r"
        )
    end.assert_called_once()


def test_invalid_domains_are_refused():
    assert client_domains.is_valid("starfire.local") and client_domains.is_valid("A.M-Rose.com.")
    for bad in ("", "not a domain", "-x.local", "x..local"):
        assert not client_domains.is_valid(bad)
    with pytest.raises(ValueError):
        client_domains.edit(
            actor=object(), client=CLIENT, domain="bad domain", action="add", reason="r"
        )


def test_the_definition_and_settings_are_data_and_the_page_edits_them():
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert (
        "SELECT 'client', 'domains', 'Domains'" in source and "'text', 'set', 'internal'" in source
    )
    assert migration.SETTINGS["min_computers"] == 2 and "workgroup" in migration.SETTINGS["ignored"]
    get_template("org_index.html")
    page = (_ROOT / "templates" / "org_index.html").read_text(encoding="utf-8")
    assert 'id="client-domains"' in page and "{% for item in domain_names %}" in page
    assert "{% url 'client_domain_edit' org_slug=current_client.slug %}" in page
