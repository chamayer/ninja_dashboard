"""Bounded PostgreSQL coverage for source-group attribution lookup."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from ingest.source_records import _load_records, evaluate_record


@pytest.fixture(scope="module")
def postgres_connection():
    if os.environ.get("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION_TESTS=1 to start disposable Postgres")
    postgres = pytest.importorskip("testcontainers.postgres")
    container = postgres.PostgresContainer("postgres:16-alpine")
    with container:
        dsn = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        with psycopg.connect(dsn) as connection:
            yield connection


def test_group_mapping_lookup_does_not_inherit_computer_client(postgres_connection):
    tenant_id = 1
    instance_id = uuid.uuid4()
    mapped_client_id = uuid.uuid4()
    computer_client_id = uuid.uuid4()
    mapped_subject_id, unmapped_subject_id, ambiguous_subject_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    mapped_observation_id, unmapped_observation_id, ambiguous_observation_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    mapped_device_id, unmapped_device_id, ambiguous_device_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    hudu_legacy_subject, hudu_native_subject = uuid.uuid4(), uuid.uuid4()
    hudu_legacy_observation, hudu_native_observation = uuid.uuid4(), uuid.uuid4()
    with postgres_connection.transaction(), postgres_connection.cursor() as cur:
        cur.execute(
            """
            CREATE SCHEMA operations;
            CREATE TABLE operations.source_record_subjects (
                id uuid PRIMARY KEY, tenant_id bigint, input_version bigint,
                association_version bigint, record_role text, presence text,
                platform text, entity_type text, source_instance_id uuid,
                external_id text, observation_id uuid, subject_kind text,
                external_namespace text, parent_external_namespace text,
                parent_external_id text
            );
            CREATE TABLE operations.entity_observation_current (
                tenant_id bigint, observation_id uuid, client_id uuid,
                canonical_data jsonb
            );
            CREATE TABLE operations.entity_source_links (
                tenant_id bigint, source_instance_id uuid, entity_class_id text,
                external_id text, entity_id uuid, missing_since timestamptz,
                external_namespace text, parent_external_namespace text,
                parent_external_id text, match_method text
            );
            CREATE TABLE operations.v_entity_observation_admin_metadata (
                tenant_id bigint, observation_id uuid, reported_online boolean,
                reported_last_contact_at timestamptz, restricted boolean
            );
            CREATE TABLE operations.devices (
                tenant_id bigint, id uuid, deleted_at timestamptz, client_id uuid
            );
            CREATE TABLE operations.entity_candidates (
                tenant_id bigint, source_instance_id uuid, external_namespace text,
                parent_external_namespace text, parent_external_id text,
                external_id text, status text
            );
            CREATE TABLE operations.findings (
                tenant_id bigint, condition_namespace text, status text,
                finding_type_id integer, finding_details jsonb, client_id uuid
            );
            CREATE TABLE operations.finding_types (id integer, name text);
            """
        )
        records = [
            (
                mapped_subject_id,
                mapped_observation_id,
                mapped_device_id,
                "mapped-group",
            ),
            (
                unmapped_subject_id,
                unmapped_observation_id,
                unmapped_device_id,
                "unmapped-group",
            ),
            (
                ambiguous_subject_id,
                ambiguous_observation_id,
                ambiguous_device_id,
                "ambiguous-group",
            ),
        ]
        for subject_id, observation_id, device_id, group_id in records:
            cur.execute(
                """
                INSERT INTO operations.source_record_subjects
                    VALUES (%s, %s, 1, 1, 'endpoint_agent', 'present', 'Ninja',
                            'agent.device', %s, %s, %s, 'record', 'device', '', '')
                """,
                (subject_id, tenant_id, instance_id, str(device_id), observation_id),
            )
            cur.execute(
                """
                INSERT INTO operations.entity_observation_current
                VALUES (%s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    observation_id,
                    computer_client_id,
                    Jsonb({"platform_group_id": group_id}),
                ),
            )
            cur.execute(
                """
                INSERT INTO operations.v_entity_observation_admin_metadata
                VALUES (%s, %s, NULL, NULL, false)
                """,
                (tenant_id, observation_id),
            )
            cur.execute(
                "INSERT INTO operations.devices VALUES (%s, %s, NULL, %s)",
                (tenant_id, device_id, computer_client_id),
            )
            cur.execute(
                """
                INSERT INTO operations.entity_source_links
                VALUES (%s, %s, 'device', %s, %s, NULL, 'device', '', '', 'test')
                """,
                (tenant_id, instance_id, str(device_id), device_id),
            )
        cur.execute(
            """
            INSERT INTO operations.entity_source_links
                VALUES (%s, %s, 'client', 'mapped-group', %s, NULL,
                        'source_group', '', '', 'test')
            """,
            (tenant_id, instance_id, mapped_client_id),
        )
        cur.execute(
            """
            INSERT INTO operations.entity_source_links
                VALUES (%s, %s, 'client', 'ambiguous-group', %s, NULL,
                        'source_group_a', '', '', 'test'),
                       (%s, %s, 'client', 'ambiguous-group', %s, NULL,
                        'source_group_b', '', '', 'test')
            """,
            (
                tenant_id,
                instance_id,
                uuid.uuid4(),
                tenant_id,
                instance_id,
                uuid.uuid4(),
            ),
        )

        for subject_id, observation_id, asset_id in (
            (hudu_legacy_subject, hudu_legacy_observation, "asset-legacy"),
            (hudu_native_subject, hudu_native_observation, "asset-native"),
        ):
            cur.execute(
                """INSERT INTO operations.source_record_subjects
                       VALUES (%s, %s, 1, 1, 'documentation', 'present', 'Hudu',
                               'cmdb.asset', %s, %s, %s, 'record', 'hudu.asset', '', '')""",
                (subject_id, tenant_id, instance_id, asset_id, observation_id),
            )
            cur.execute(
                """INSERT INTO operations.entity_observation_current
                       VALUES (%s, %s, NULL, %s)""",
                (tenant_id, observation_id, Jsonb({"link_verdict": "stale"})),
            )
        cur.execute(
            "INSERT INTO operations.finding_types VALUES (900, 'cmdb_asset_stale')"
        )
        cur.execute(
            """INSERT INTO operations.findings
                   VALUES (1, 'entity', 'open', 900,
                           %s::jsonb, NULL)""",
            (
                Jsonb(
                    {
                        "asset_id": "asset-legacy",
                        "source_instance_id": str(instance_id),
                    }
                ),
            ),
        )

        loaded = {
            row["id"]: row
            for row in _load_records(
                cur,
                tenant_id,
                [
                    mapped_subject_id,
                    unmapped_subject_id,
                    ambiguous_subject_id,
                    hudu_legacy_subject,
                    hudu_native_subject,
                ],
            )
        }

        assert loaded[mapped_subject_id]["source_group_client_id"] == mapped_client_id
        assert loaded[mapped_subject_id]["device_client_id"] == computer_client_id
        assert loaded[unmapped_subject_id]["source_group_client_id"] is None
        # This is the fallback value that must not be mistaken for a group map.
        assert loaded[unmapped_subject_id]["device_client_id"] == computer_client_id
        assert loaded[ambiguous_subject_id]["source_group_client_id"] is None
        mapped_result = next(
            item
            for item in evaluate_record(loaded[mapped_subject_id], {})
            if item["rule"] == "record.source_attribution"
        )
        unmapped_result = next(
            item
            for item in evaluate_record(loaded[unmapped_subject_id], {})
            if item["rule"] == "record.source_attribution"
        )
        ambiguous_result = next(
            item
            for item in evaluate_record(loaded[ambiguous_subject_id], {})
            if item["rule"] == "record.source_attribution"
        )
        assert mapped_result["result"] == "contradicted"
        assert mapped_result["owner"] == "legacy:computer_client_conflict"
        assert unmapped_result["result"] == "unknown"
        assert ambiguous_result["result"] == "unknown"
        hudu_legacy_result = next(
            item
            for item in evaluate_record(loaded[hudu_legacy_subject], {})
            if item["rule"] == "record.reference"
        )
        hudu_native_result = next(
            item
            for item in evaluate_record(loaded[hudu_native_subject], {})
            if item["rule"] == "record.reference"
        )
        assert hudu_legacy_result["owner"] == "legacy:cmdb_asset_stale"
        assert hudu_legacy_result["finding"] is None
        assert hudu_native_result["finding"]["type"] == "source_record_reference_review"
