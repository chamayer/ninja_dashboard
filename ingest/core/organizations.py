"""Organizations ingest.

Source: GET /v2/organizations (paginate_after).
Target: ninja_core.organizations (upsert on id).
"""

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient) -> int:
    """Fetch all organizations and upsert. Returns row count."""
    raise NotImplementedError
