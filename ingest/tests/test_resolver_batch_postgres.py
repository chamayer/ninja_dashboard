import os
import uuid

import psycopg
import pytest

from ingest.identity import resolver


def test_batch_rereads_changed_and_no_longer_eligible_records(monkeypatch):
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1")
    postgres = pytest.importorskip("testcontainers.postgres")
    identifiers = [uuid.uuid4() for _ in range(3)]
    with postgres.PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA operations;
                CREATE TABLE operations.entity_observation_current (
                    tenant_id bigint, observation_id uuid, entity_type text,
                    entity_key text, platform text, observed_at timestamptz,
                    canonical_data jsonb, source_instance_id uuid,
                    device_id uuid, active boolean);
                CREATE FUNCTION operations.computer_client_independent_evidence(bigint,uuid)
                RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;
            """)
            for identifier in identifiers:
                cur.execute(
                    "INSERT INTO operations.entity_observation_current VALUES (1,%s,'agent.rmm','record','Ninja',now(),%s::jsonb,%s,NULL,true)",
                    (
                        identifier,
                        '{"hostname":"test","serial_number":"old"}',
                        uuid.uuid4(),
                    ),
                )
            cur.execute(
                "UPDATE operations.entity_observation_current SET device_id=%s WHERE observation_id=%s",
                (uuid.uuid4(), identifiers[0]),
            )
            cur.execute(
                "UPDATE operations.entity_observation_current SET active=false WHERE observation_id=%s",
                (identifiers[1],),
            )
            cur.execute(
                "UPDATE operations.entity_observation_current SET canonical_data=canonical_data || %s::jsonb WHERE observation_id=%s",
                ('{"serial_number":"current"}', identifiers[2]),
            )
            seen = []
            monkeypatch.setattr(
                resolver, "identity_entity_types", lambda _: {"agent.rmm"}
            )
            monkeypatch.setattr(resolver, "load_identity_match_policies", lambda *_: ())
            monkeypatch.setattr(resolver, "_load_finding_type_id", lambda *_: 1)
            monkeypatch.setattr(resolver, "record_name_short", lambda *_: "test")
            monkeypatch.setattr(
                resolver,
                "resolve_device_by_policy",
                lambda cur, **kw: seen.append(kw["serial"]),
            )
            monkeypatch.setattr(
                resolver, "_maybe_create_candidate", lambda *a, **kw: None
            )
            monkeypatch.setattr(resolver, "write_computer_names", lambda *_: None)
            assert resolver._resolve_observation_batch(cur, identifiers) == (0, 1)
            assert seen == ["current"]
