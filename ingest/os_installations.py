"""Project OS-installation anchors and their current Computer relationship.

Computers remain ``operations.devices``.  An ``agent.*`` observation is about
an OS installation and also reports evidence about the Computer it runs on;
``vm.guest`` does not create an OS installation.  The projector groups active
agent observations already attached to the same Computer into one OS
installation unless a stable agent-record identity has already established a
different installation.  A source identity that later appears on another
Computer carries that OS installation with it, preserving a dated ``runs on``
relationship without using a hostname as proof.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from ingest import db, relationships

log = logging.getLogger(__name__)

TENANT_ID = 1
RELATIONSHIP_TYPE = "os_installation_runs_on_computer"
NATIVE_RECORD_TYPE = "agent_observation"
OS_ENDPOINT_NAMESPACE = "os_installation"


def _relation_id(row: tuple) -> str:
    source_instance_id, namespace, parent_namespace, parent_id, external_id = row[:5]
    material = "\x1f".join(
        (str(source_instance_id), namespace, parent_namespace, parent_id, external_id)
    )
    return f"os-installation-runs-on:{hashlib.sha256(material.encode()).hexdigest()}"


def _create_installation(
    cur, *, client_id, observed_at: datetime
) -> tuple[uuid.UUID, uuid.UUID]:
    entity_id = uuid.uuid4()
    installation_id = uuid.uuid4()
    cur.execute(
        """
        INSERT INTO operations.entities (
            id, tenant_id, entity_class_id, scope_kind, client_id, version,
            created_at, created_reason, updated_at, updated_reason,
            retired_at, retired_reason, deleted_at, deleted_reason
        ) VALUES (
            %s, %s, 'os_installation', 'client', %s, 1,
            %s, 'identity.os_installation_from_agent', %s,
            'identity.os_installation_from_agent', NULL, '', NULL, ''
        )
        """,
        (entity_id, TENANT_ID, client_id, observed_at, observed_at),
    )
    cur.execute(
        """
        INSERT INTO operations.operating_system_installations (
            id, tenant_id, version, entity_id, client_id,
            first_observed_at, last_observed_at, retired_at, retired_reason
        ) VALUES (%s, %s, 1, %s, %s, %s, %s, NULL, '')
        """,
        (installation_id, TENANT_ID, entity_id, client_id, observed_at, observed_at),
    )
    return installation_id, entity_id


def _find_installation_for_computer(
    cur, *, device_id
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Return an active OS installation already evidenced on this Computer."""
    cur.execute(
        """
        SELECT identity.installation_id, installation.entity_id
          FROM operations.operating_system_installation_source_identities identity
          JOIN operations.operating_system_installations installation
            ON installation.tenant_id = identity.tenant_id
           AND installation.id = identity.installation_id
          JOIN operations.entity_observation_current observation
            ON observation.tenant_id = identity.tenant_id
           AND observation.source_instance_id = identity.source_instance_id
           AND observation.external_namespace = identity.external_namespace
           AND observation.parent_external_namespace = identity.parent_external_namespace
           AND observation.parent_external_id = identity.parent_external_id
           AND observation.external_id = identity.external_id
         WHERE identity.tenant_id = %s
           AND observation.active
           AND observation.entity_type LIKE 'agent.%%'
           AND observation.device_id = %s
           AND installation.retired_at IS NULL
         ORDER BY identity.first_observed_at, identity.id
         LIMIT 1
        """,
        (TENANT_ID, device_id),
    )
    return cur.fetchone()


def project_all() -> dict[str, int | str]:
    """Build OS-installation source identities and their active host evidence."""
    totals: dict[str, int | str] = {
        "status": "complete",
        "installations_created": 0,
        "source_identities_created": 0,
        "relationships_written": 0,
        "relationships_withdrawn": 0,
    }
    with db.transaction() as cur:
        cur.execute("SET LOCAL operations.tenant_id = %s", (TENANT_ID,))
        cur.execute(
            "SELECT to_regclass('operations.operating_system_installations') IS NOT NULL"
        )
        if not cur.fetchone()[0]:
            totals["status"] = "migration_pending"
            return totals
        cur.execute(
            """
            SELECT observation.source_instance_id, observation.external_namespace,
                   observation.parent_external_namespace, observation.parent_external_id,
                   observation.external_id, observation.device_id, observation.client_id,
                   observation.observed_at, observation.last_seen_at, device.entity_id
              FROM operations.entity_observation_current observation
              JOIN operations.devices device
                ON device.tenant_id = observation.tenant_id
               AND device.id = observation.device_id
             WHERE observation.tenant_id = %s
               AND observation.active
               AND observation.entity_type LIKE 'agent.%%'
               AND observation.device_id IS NOT NULL
               AND observation.client_id IS NOT NULL
               AND device.deleted_at IS NULL
               AND device.entity_id IS NOT NULL
             ORDER BY observation.source_instance_id, observation.external_namespace,
                      observation.parent_external_namespace, observation.parent_external_id,
                      observation.external_id
            """,
            (TENANT_ID,),
        )
        rows = cur.fetchall()
        for row in rows:
            (
                source_instance_id,
                namespace,
                parent_namespace,
                parent_id,
                external_id,
                device_id,
                client_id,
                observed_at,
                last_seen_at,
                computer_entity_id,
            ) = row
            cur.execute(
                """
                SELECT identity.installation_id, installation.entity_id,
                       installation.client_id
                  FROM operations.operating_system_installation_source_identities identity
                  JOIN operations.operating_system_installations installation
                    ON installation.tenant_id = identity.tenant_id
                   AND installation.id = identity.installation_id
                 WHERE identity.tenant_id = %s
                   AND identity.source_instance_id = %s
                   AND identity.external_namespace = %s
                   AND identity.parent_external_namespace = %s
                   AND identity.parent_external_id = %s
                   AND identity.external_id = %s
                 FOR UPDATE
                """,
                (
                    TENANT_ID,
                    source_instance_id,
                    namespace,
                    parent_namespace,
                    parent_id,
                    external_id,
                ),
            )
            identity = cur.fetchone()
            if identity is None:
                existing = _find_installation_for_computer(cur, device_id=device_id)
                if existing is None:
                    installation_id, installation_entity_id = _create_installation(
                        cur, client_id=client_id, observed_at=observed_at
                    )
                    totals["installations_created"] += 1
                else:
                    installation_id, installation_entity_id = existing
                cur.execute(
                    """
                    INSERT INTO operations.operating_system_installation_source_identities (
                        id, tenant_id, version, installation_id, source_instance_id,
                        external_namespace, parent_external_namespace, parent_external_id,
                        external_id, first_observed_at, last_observed_at
                    ) VALUES (
                        %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        uuid.uuid4(),
                        TENANT_ID,
                        installation_id,
                        source_instance_id,
                        namespace,
                        parent_namespace,
                        parent_id,
                        external_id,
                        observed_at,
                        last_seen_at,
                    ),
                )
                totals["source_identities_created"] += 1
            else:
                installation_id, installation_entity_id, installation_client_id = (
                    identity
                )
                if installation_client_id != client_id:
                    # A source record changing client scope is not evidence that an OS
                    # installation moved across customers. Leave it for identity review.
                    continue
                cur.execute(
                    """
                    UPDATE operations.operating_system_installation_source_identities
                       SET last_observed_at = GREATEST(last_observed_at, %s),
                           version = version + 1
                     WHERE tenant_id = %s AND source_instance_id = %s
                       AND external_namespace = %s
                       AND parent_external_namespace = %s
                       AND parent_external_id = %s AND external_id = %s
                    """,
                    (
                        last_seen_at,
                        TENANT_ID,
                        source_instance_id,
                        namespace,
                        parent_namespace,
                        parent_id,
                        external_id,
                    ),
                )

            relation_key = _relation_id(row)
            relationships.write_current_evidence(
                cur,
                tenant_id=TENANT_ID,
                source_instance_id=source_instance_id,
                native_record_type=NATIVE_RECORD_TYPE,
                external_relationship_id=relation_key,
                relationship_type=RELATIONSHIP_TYPE,
                source_endpoint={
                    "source_instance_id": source_instance_id,
                    "external_namespace": OS_ENDPOINT_NAMESPACE,
                    "external_id": external_id,
                    "parent_external_namespace": parent_namespace,
                    "parent_external_id": parent_id,
                },
                target_endpoint={
                    "source_instance_id": source_instance_id,
                    "external_namespace": namespace,
                    "external_id": external_id,
                    "parent_external_namespace": parent_namespace,
                    "parent_external_id": parent_id,
                },
                material_hash=hashlib.sha256(
                    f"{installation_entity_id}:{computer_entity_id}".encode()
                ).digest(),
                observed_at=last_seen_at,
            )
            cur.execute(
                """
                UPDATE operations.entity_relationship_evidence_current
                   SET source_entity_id = %s, target_entity_id = %s,
                       version = version + 1
                 WHERE tenant_id = %s AND source_instance_id = %s
                   AND external_relationship_id = %s
                """,
                (
                    installation_entity_id,
                    computer_entity_id,
                    TENANT_ID,
                    source_instance_id,
                    relation_key,
                ),
            )
            cur.execute(
                """
                UPDATE operations.entity_relationship_evidence_history history
                   SET source_entity_id = current.source_entity_id,
                       target_entity_id = current.target_entity_id,
                       resolution_status = current.resolution_status,
                       authority_eligible = current.authority_eligible,
                       authority_tier = current.authority_tier,
                       authority_priority = current.authority_priority
                  FROM operations.entity_relationship_evidence_current current
                 WHERE history.tenant_id = current.tenant_id
                   AND history.evidence_current_id = current.id
                   AND current.tenant_id = %s
                   AND current.source_instance_id = %s
                   AND current.external_relationship_id = %s
                   AND history.effective_to IS NULL
                """,
                (TENANT_ID, source_instance_id, relation_key),
            )
            totals["relationships_written"] += 1

        withdrawn_at = datetime.now(timezone.utc)
        cur.execute(
            """
            UPDATE operations.entity_relationship_evidence_current relationship
               SET active = FALSE, withdrawn_at = %s, version = version + 1
             WHERE relationship.tenant_id = %s
               AND relationship.relationship_type_id = %s
               AND relationship.native_record_type = %s
               AND relationship.active
               AND NOT EXISTS (
                    SELECT 1
                      FROM operations.entity_observation_current observation
                     WHERE observation.tenant_id = relationship.tenant_id
                       AND observation.source_instance_id = relationship.source_endpoint_source_instance_id
                       AND observation.external_namespace = relationship.target_external_namespace
                       AND observation.parent_external_namespace = relationship.target_parent_external_namespace
                       AND observation.parent_external_id = relationship.target_parent_external_id
                       AND observation.external_id = relationship.target_external_id
                       AND observation.active
                       AND observation.entity_type LIKE 'agent.%%'
               )
            RETURNING id
            """,
            (withdrawn_at, TENANT_ID, RELATIONSHIP_TYPE, NATIVE_RECORD_TYPE),
        )
        withdrawn_ids = [item[0] for item in cur.fetchall()]
        if withdrawn_ids:
            cur.execute(
                """
                UPDATE operations.entity_relationship_evidence_history
                   SET effective_to = %s
                 WHERE tenant_id = %s AND evidence_current_id = ANY(%s)
                   AND effective_to IS NULL AND effective_from < %s
                """,
                (withdrawn_at, TENANT_ID, withdrawn_ids, withdrawn_at),
            )
            totals["relationships_withdrawn"] = len(withdrawn_ids)
    log.info("OS-installation projection: %s", totals)
    return totals
