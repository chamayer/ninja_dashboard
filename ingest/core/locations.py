"""Locations ingest.

Source: GET /v2/locations (paginate_after).
Target: ninja_core.locations (upsert on id).
"""

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient) -> int:
    """Fetch all locations and upsert. Returns row count."""
    raise NotImplementedError
