"""The resolver promotes a client candidate only on strong evidence (ADR-0041)."""

from __future__ import annotations

from ingest.identity import client_resolver

SETTINGS = {**client_resolver._PROMOTION_DEFAULTS, "create_required_source": "Ninja"}
PROMPT = {"client_id": "prompt", "display_name": "Prompt", "record_count": 3}
LIVE = [(5, "ruon-mda")]


def _decide(matches, sources=("R-U-ON",), separate=None, live=LIVE, **overrides):
    return client_resolver._promotion_decision(
        {**SETTINGS, **overrides}, live, list(sources), matches, separate or {}
    )


def test_maps_when_enough_names_belong_only_to_one_client():
    assert _decide([PROMPT]) == ("prompt", "3 computer names in R-U-ON belong only to Prompt")


def test_one_name_two_clients_or_a_separate_group_is_not_enough():
    assert _decide([{**PROMPT, "record_count": 1}]) is None
    assert _decide([PROMPT, {**PROMPT, "client_id": "other"}]) is None
    # Prompt already has its own R-U-ON group: R-U-ON keeps them apart.
    assert _decide([PROMPT], separate={"prompt": {5}}) is None
    assert _decide([PROMPT], map_enabled=False) is None


def test_creates_a_provisional_client_when_several_sources_including_the_required_one_agree():
    live = [(1, "77"), (2, "4")]
    assert _decide([], sources=("Hudu", "Ninja"), live=live) == (
        None,
        "Reported by Hudu, Ninja; no existing client",
    )
    # A spinoff: the clients its names point to are kept separate by these sources.
    nycd = _decide(
        [{**PROMPT, "display_name": "City Painting", "client_id": "cp"}],
        sources=("Hudu", "Ninja"),
        live=live,
        separate={"cp": {1, 2}},
        map_enabled=False,
    )
    assert nycd == (
        None,
        "Reported by Hudu, Ninja; no existing client; kept separate from City Painting",
    )


def test_no_creation_without_the_required_source_enough_sources_or_the_switch():
    live = [(1, "77"), (2, "4")]
    assert _decide([], sources=("Hudu", "SentinelOne"), live=live) is None
    assert _decide([], sources=("Ninja",), live=live[:1]) is None
    assert _decide([], sources=("Hudu", "Ninja"), live=live, create_enabled=False) is None
    assert _decide([], sources=("Hudu", "Ninja"), live=live, create_required_source="") is None
    # A name pointing to a client the sources do not keep separate stops creation.
    assert _decide([{**PROMPT, "record_count": 1}], sources=("Hudu", "Ninja"), live=live) is None


def test_settings_fall_back_to_code_defaults_for_missing_keys():
    class _Cursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return ({"map_min_names": 3},)

    settings = client_resolver._promotion_settings(_Cursor())
    assert settings["map_min_names"] == 3 and settings["map_enabled"] is True
    assert settings["create_required_source"] == ""
