"""Contract tests for `promote_candidate` -- generic entity anchor creation.

Source-inspection tests in the style of `test_e4_generic_contract.py`: they run
without a database, which is what lets them guard the properties that only
matter at the moment somebody edits this file.

The property that matters most is the typed-twin guard. `device` and `client`
anchors are created by reusing the typed row's UUID, so every anchor of those
classes has a `devices` / `clients` row behind it. A bare anchor would satisfy
no such invariant, and nothing else in the schema would object -- the FKs point
from the typed table to `entities`, not back.
"""

from __future__ import annotations

import inspect

from apps.core import entity_candidate_decisions as decisions


def test_promotion_is_atomic_and_guards_classes_with_a_typed_record() -> None:
    source = inspect.getsource(decisions.promote_candidate)

    assert "_assert_class_has_no_typed_record" in source
    assert "_authorize" in source
    assert "select_for_update" in source
    # A reason is mandatory: nothing enters the entity store without why.
    assert "A candidate decision reason is required." in source


def test_promotion_refuses_terminal_candidates() -> None:
    source = inspect.getsource(decisions.promote_candidate)

    assert "Status.ATTACHED" in source
    assert "Status.REJECTED" in source


def test_scope_follows_ownership_not_a_constant() -> None:
    """ADR-0012 s4, and what `ck_entities_scope_owner` enforces."""
    source = inspect.getsource(decisions.promote_candidate)

    assert "ScopeKind.CLIENT if locked.client_id else" in source
    assert "client_id=locked.client_id" in source


def test_link_creation_is_shared_with_attach_not_duplicated() -> None:
    """One link/history path, so promotion cannot drift from attachment."""
    promote = inspect.getsource(decisions.promote_candidate)
    attach = inspect.getsource(decisions.attach_candidate)

    assert "_link_candidate_to_entity" in promote
    assert "_link_candidate_to_entity" in attach
    for body in (promote, attach):
        assert "EntitySourceLinkHistory.objects.create" not in body


def test_promotion_is_recorded_as_its_own_action() -> None:
    """`attach` and `promote` are different decisions and must audit apart."""
    source = inspect.getsource(decisions.promote_candidate)

    assert 'action="promote"' in source
    assert 'latest_decision = "promote"' in source


def test_typed_twin_guard_asks_the_data_rather_than_listing_class_names() -> None:
    """A hardcoded class list would be an ADR-0012 s6 domain mapping in code."""
    source = inspect.getsource(decisions.class_supports_promotion)

    assert "Device.objects.filter" in source
    assert "Client.objects.filter" in source
    assert '"device"' not in source
    assert '"client"' not in source
