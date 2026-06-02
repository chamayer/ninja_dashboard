"""Policies ingest.

Source: GET /v2/policies (no pagination per the OpenAPI spec).
Target: ninja_core.policies (upsert on id).
"""

from ingest.ninja_client import NinjaClient


def run(client: NinjaClient) -> int:
    """Fetch all policies and upsert. Returns row count."""
    raise NotImplementedError
