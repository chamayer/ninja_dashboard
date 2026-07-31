"""Move source/entity mappings out of Python literals into data.

`ingest/source_observations.py` states the rule at the top of the file:
"Registering a new source means seeding its operations.source_bindings row; no
code changes required here. Fetchers are the only thing keyed by platform
(they are code, not config)." Three lookups violated it, so registering a
source in fact required editing three Python literals in three files, and
missing any one meant the source collected nothing.

* ``operations.entity_types`` — replaces the `IDENTITY_ENTITY_TYPES` frozenset.
  `is_identity_signal` decides whether an observation kind may create a Device,
  write device_links, and participate in identity-driven collection behavior.
  Lifecycle eligibility is separately controlled by
  `lifecycle_evidence_mode` in migration 0093. That is the most consequential
  rule in the platform and it was a literal in a source file, changeable only
  by deploy.
* ``operations.platform_aliases`` — replaces `normalize.PLATFORM_ALIASES`.
  Matches the existing `client_name_aliases` / `publisher_aliases` pattern.
  A missing alias meant the platform name failed to canonicalise, missed the
  fetcher lookup, and the source was skipped in silence.
* ``operations.sources.entity_type`` — replaces `sources._KIND_ENTITY_TYPE`.
  Held directly on the source rather than derived from `kind` through a
  dictionary, so a new source kind needs no code.

Not touching `operations.agents`: that table is the requirement universe
(RequirementProfileItem FKs to it), and a CMDB is not something a client is
required to have installed. Its `entity_type` column stays as-is.

Grants mirror the sibling reference tables, including `ninja_ingest=r` as on
`agents` — the ingest service reads all three at collection time.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
-- ── entity_types ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operations.entity_types (
    name               varchar(80) PRIMARY KEY,
    is_identity_signal boolean     NOT NULL DEFAULT FALSE,
    description        text        NOT NULL DEFAULT ''
);

INSERT INTO operations.entity_types (name, is_identity_signal, description) VALUES
    ('agent.rmm',            TRUE,  'RMM agent installed on the machine.'),
    ('agent.edr',            TRUE,  'EDR agent installed on the machine.'),
    ('agent.remote_access',  TRUE,  'Remote-access agent installed on the machine.'),
    ('vm.host',              TRUE,  'Hypervisor host reported by its own agent.'),
    ('vm.guest',             TRUE,  'VM guest reported by the hypervisor.'),
    ('network.device',       TRUE,  'Network device discovered by a monitoring probe.'),
    ('monitor.target',       TRUE,  'Monitored target discovered by a probe.'),
    ('cmdb.asset',           FALSE, 'CMDB documentation record. Describes a thing; is not evidence the thing was reached.'),
    ('software',             FALSE, 'Software installation on a device. Device-scoped attribute, not identity.'),
    ('org',                  FALSE, 'Source-side container/organisation. Resolves to a client, never a device.'),
    ('unknown',              FALSE, 'Unclassified stream. Never treated as identity evidence.')
ON CONFLICT (name) DO NOTHING;

-- ── platform_aliases ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operations.platform_aliases (
    alias     varchar(80) PRIMARY KEY,
    canonical varchar(80) NOT NULL
);

INSERT INTO operations.platform_aliases (alias, canonical) VALUES
    ('ninja',         'Ninja'),
    ('sentinelone',   'SentinelOne'),
    ('s1',            'SentinelOne'),
    ('logmein',       'LogMeIn'),
    ('lmi',           'LogMeIn'),
    ('screenconnect', 'ScreenConnect'),
    ('sc',            'ScreenConnect'),
    ('hudu',          'Hudu')
ON CONFLICT (alias) DO NOTHING;

-- ── sources.entity_type ──────────────────────────────────────────────
ALTER TABLE operations.sources
    ADD COLUMN IF NOT EXISTS entity_type varchar(80) NOT NULL DEFAULT '';

UPDATE operations.sources SET entity_type = CASE kind
        WHEN 'rmm'            THEN 'agent.rmm'
        WHEN 'edr'            THEN 'agent.edr'
        WHEN 'remote_access'  THEN 'agent.remote_access'
        WHEN 'cmdb'           THEN 'cmdb.asset'
        ELSE ''
    END
 WHERE entity_type = '';

-- ── grants: mirror the sibling reference tables ──────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.entity_types    TO operations_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON operations.platform_aliases TO operations_app;
GRANT SELECT ON operations.entity_types,    operations.platform_aliases TO operations_readonly;
GRANT SELECT ON operations.entity_types,    operations.platform_aliases TO metabase_ro;
GRANT SELECT ON operations.entity_types,    operations.platform_aliases TO ninja_ingest;
"""

REVERSE_SQL = """
ALTER TABLE operations.sources DROP COLUMN IF EXISTS entity_type;
DROP TABLE IF EXISTS operations.platform_aliases;
DROP TABLE IF EXISTS operations.entity_types;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0091_cmdb_finding_types"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
