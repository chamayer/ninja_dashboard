"""Migration 0123 — retire ``operations.client_links`` (E6).

The client-side twin of ``device_links`` (migration 0121, ADR-0014). Four code
paths wrote it: ``source_observations._upsert_client_links``,
``client_resolver._attach_group``, ``views._attach_group_to_client``, and the
``bootstrap_clients_from_ninja`` management command. It is replaced by
``operations.v_client_source_link`` over ``operations.entity_source_links``,
which ``sync_entity_source_links_from_observations()`` derives from
observation evidence.

Mapping verified against production 2026-08-06: 320 rows on both sides, with
one benign difference each way — ScreenConnect's instance-level key was
renamed ``sc_uta`` to ``self`` for the same client. **Zero** clients disagree
about which entity a source identity attaches to.

Unlike the device side there is no companion namespace to exclude. Each source
contributes exactly one: ``company`` (Hudu), ``group`` (LogMeIn),
``organization`` (Ninja), ``site`` (SentinelOne), ``source-instance``
(ScreenConnect). So this view needs no aggregation and cannot repeat the
~365x regression that the device-side compatibility view produced.

There is also no same-transaction ordering trap. ``_load_client_links`` and
``_upsert_client_links`` sat in one transaction, but the read was first and
the write last, so the lookup only ever served links from earlier cycles.
``entity_source_links`` is synced at the collection boundary, which gives the
same staleness.

**What this fixes.** ``client_name_conflict`` had produced zero findings and
could not produce one. The detector suppressed the finding when the observed
source name matched *either* the canonical client name or the stored
``client_links.external_name`` — while ``_attach_group`` refreshed that column
to the observed name on every sync. The second comparison tested the observed
value against itself. Measured across all 320 links: 264 matched the canonical
client name, **319** matched the stored name, and 1 matched neither. Removing
the self-referential term surfaces **56** real name drifts.

This is the same defect class as the ``WHERE s.name = 'Ninja'`` filter that
motivated retiring ``device_links``: a column maintained in a way that
disables the finding that reads it, invisible from row counts.

**``external_name`` is deliberately not reproduced.** The attribute contract
could not supply it in any case — ``claim(name)`` is keyed per
(client, source_instance) while ``external_name`` is per
(source, external_id); a client with ten LogMeIn groups has ten external names
and one name claim, and the join fans 320 links to 522 rows with 204
differing. More importantly, suppressing a drift is a decision that belongs to
an operator and should be recorded as one. A column silently rewritten on
every sync is not that. An explicit "accepted name" is a reasonable future
feature; keeping the drift hidden until it exists is not.

**``bootstrap_clients_from_ninja`` is retired with it.** BLUEPRINT Track C
superseded it on 2026-07-13 — "no source is a client authority" — and
scheduled its removal as C.7, which never happened. It ran from
``entrypoint.sh`` on every container start and was a measured no-op
(``created=0 updated=0 unchanged=75 total=75``), but it would have auto-minted
a client for any new Ninja org, which Track C forbids.

Not reversible. ``external_name``, ``created_reason`` and the row identities
are not reconstructible.
"""

from typing import ClassVar

from django.db import migrations, models

CREATE_VIEW_SQL = r"""
CREATE VIEW operations.v_client_source_link
WITH (security_invoker = true) AS
SELECT link.id,
       link.tenant_id,
       link.entity_id                  AS client_id,
       instance.source_id,
       link.external_id::varchar(240)  AS external_id,
       link.external_namespace,
       link.first_seen_at,
       link.last_seen_at,
       link.missing_since
FROM operations.entity_source_links link
JOIN operations.source_instances instance
  ON instance.id = link.source_instance_id
WHERE link.entity_class_id = 'client';

ALTER VIEW operations.v_client_source_link OWNER TO operations_migrate;

GRANT SELECT ON operations.v_client_source_link
    TO operations_app, operations_readonly, metabase_ro, ninja_ingest;

-- Read models grant SELECT only; see migration 0122 and operations/AGENTS.md.
-- ALTER DEFAULT PRIVILEGES would otherwise hand operations_app full DML here.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON operations.v_client_source_link
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
"""


PARITY_SQL = r"""
DO $block$
DECLARE
    v_old   bigint;
    v_new   bigint;
    v_moved bigint;
BEGIN
    SELECT count(*) INTO v_old FROM operations.client_links;
    SELECT count(*) INTO v_new FROM operations.v_client_source_link;

    -- The membership difference is allowed to be small (a renamed
    -- ScreenConnect instance key), but no source identity may change which
    -- client it attaches to. That is the invariant worth failing on.
    SELECT count(*) INTO v_moved
      FROM operations.client_links cl
      JOIN operations.v_client_source_link vl
        ON vl.tenant_id = cl.tenant_id
       AND vl.source_id = cl.source_id
       AND vl.external_id = cl.external_id
     WHERE vl.client_id <> cl.client_id;

    IF v_moved <> 0 THEN
        RAISE EXCEPTION
            'client attachment differs for % source identities; refusing to '
            'retire client_links', v_moved;
    END IF;

    RAISE NOTICE
        'client link parity: % old rows, % new rows, 0 reattached clients',
        v_old, v_new;
END
$block$;
"""


DROP_SQL = "DROP TABLE operations.client_links;"


class Migration(migrations.Migration):
    atomic = True

    dependencies: ClassVar = [
        ("operations", "0122_read_models_are_read_only"),
    ]

    operations: ClassVar = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(CREATE_VIEW_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(PARITY_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(DROP_SQL, migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.DeleteModel(name="ClientLink"),
                # State-only: `managed = False` emits no DDL. The relation is
                # created by CREATE_VIEW_SQL above.
                migrations.CreateModel(
                    name="ClientSourceLink",
                    fields=[
                        ("id", models.UUIDField(primary_key=True, serialize=False)),
                        ("external_id", models.CharField(max_length=240)),
                        ("external_namespace", models.CharField(max_length=120)),
                        ("first_seen_at", models.DateTimeField(blank=True, null=True)),
                        ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                        ("missing_since", models.DateTimeField(blank=True, null=True)),
                    ],
                    options={
                        "db_table": "v_client_source_link",
                        "managed": False,
                    },
                ),
            ],
        ),
    ]
