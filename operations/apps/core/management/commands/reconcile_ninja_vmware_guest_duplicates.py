"""Combine Computers proven identical by Ninja VMware guest VMX-path evidence.

The default is a read-only measurement.  Apply mode requires the exact group
count and a deterministic digest from that measurement, so a changed source
population cannot be combined accidentally.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.views import _merge_devices

_MIN_COMPUTERS_TO_COMBINE = 2


@dataclass(frozen=True)
class VmwareGuestGroup:
    organization_id: str
    vmx_path: str
    device_ids: tuple[str, ...]


def _groups() -> list[VmwareGuestGroup]:
    """Return only same-organization, exact-VMX-path Computer splits.

    The source payload is retained on inactive observations, so this includes
    the historical Ninja node records that were created by normal host moves.
    A storage-path change has a different path and is intentionally excluded.
    """
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL operations.tenant_id = 1")
        cur.execute(
            """
            WITH guest_evidence AS (
                SELECT lower(regexp_replace(
                           COALESCE(NULLIF(observation.canonical_data->>'vmx_path_normalized', ''),
                                    observation.raw_data->>'files', ''),
                           '\\s+', ' ', 'g'
                       )) AS vmx_path,
                       COALESCE(observation.canonical_data->>'ninja_organization_id',
                                observation.raw_data->>'organizationId', '') AS organization_id,
                       observation.device_id,
                       device.client_id
                  FROM operations.entity_observation_current observation
                  JOIN operations.devices device
                    ON device.tenant_id = observation.tenant_id
                   AND device.id = observation.device_id
                   AND device.deleted_at IS NULL
                 WHERE observation.tenant_id = 1
                   AND observation.platform = 'Ninja'
                   AND observation.entity_type = 'vm.guest'
            ), grouped AS (
                SELECT organization_id, vmx_path,
                       array_agg(DISTINCT device_id::text ORDER BY device_id::text) AS device_ids,
                       count(DISTINCT client_id) AS client_count
                  FROM guest_evidence
                 WHERE organization_id <> ''
                   AND vmx_path LIKE '%%.vmx'
                 GROUP BY organization_id, vmx_path
                HAVING count(DISTINCT device_id) > 1
            )
            SELECT organization_id, vmx_path, device_ids
              FROM grouped
             WHERE client_count = 1
             ORDER BY organization_id, vmx_path
            """
        )
        return [
            VmwareGuestGroup(row[0], row[1], tuple(row[2]))
            for row in cur.fetchall()
        ]


def _digest(groups: list[VmwareGuestGroup]) -> str:
    payload = "\n".join(
        f"{group.organization_id}|{group.vmx_path}|{','.join(group.device_ids)}"
        for group in groups
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Command(BaseCommand):
    help = "Measure or combine exact Ninja VMware guest VMX-path Computer splits."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-groups", type=int)
        parser.add_argument("--expected-digest")

    def handle(self, *args, **options) -> None:
        apply = bool(options["apply"])
        groups = _groups()
        digest = _digest(groups)
        device_count = sum(len(group.device_ids) for group in groups)
        self.stdout.write(
            f"groups={len(groups)} computers={device_count} digest={digest} apply={apply}"
        )
        if not apply:
            return

        if options["expected_groups"] != len(groups) or options["expected_digest"] != digest:
            raise CommandError(
                "Apply requires the exact --expected-groups and --expected-digest "
                "from a current dry run."
            )

        merged = 0
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL operations.tenant_id = 1")
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext('operations.vmware_vmx_reconcile'))"
            )
            # Re-measure under the transaction lock: the reviewed target set
            # must still be identical at the moment mutations begin.
            locked_groups = _groups()
            if _digest(locked_groups) != digest:
                raise CommandError("VMware guest target set changed; run a new dry run.")

            for group in locked_groups:
                cur.execute(
                    """
                    SELECT id::text
                      FROM operations.devices
                     WHERE tenant_id = 1 AND id = ANY(%s::uuid[])
                       AND deleted_at IS NULL
                     ORDER BY created_at, id
                     FOR UPDATE
                    """,
                    (list(group.device_ids),),
                )
                members = [row[0] for row in cur.fetchall()]
                if len(members) < _MIN_COMPUTERS_TO_COMBINE:
                    continue
                survivor = members[0]
                for loser in members[1:]:
                    _merge_devices(
                        cur,
                        survivor,
                        loser,
                        "ninja.vmware_vmx_path_identity",
                    )
                    merged += 1
            cur.execute("SELECT operations.sync_entity_source_links_from_observations()")

        self.stdout.write(self.style.SUCCESS(f"combined={merged}"))
