# ScreenConnect source configuration

ScreenConnect Access sessions use the existing source-instance, binding, Jobs,
observation, client resolution, and Computer identity pipeline. No separate
Computer population or schema is required.

Client-specific instances retain `is_shared: false`, their assigned client,
and organization observation identity `source-instance/self`.

For a separate shared instance, configure `is_shared: true`, leave its
`client_id` empty, and set `screenconnect_group_field` to the confirmed customer
property (`CustomProperty1` through `CustomProperty8`) in the instance config.
Keep the existing `base_url`, `ext_guid_ref`, and `secret_key_ref` connection
contract; the references name private runtime environment variables, never
secret values. Do not change an existing client-specific instance to shared:
use a separate instance so its observations and mapping history remain distinct.

Confirm the field against the actual instance before configuring it. The
collector reads the selected key in `CustomProperties`, with the corresponding
zero-based `CustomPropertyValues` slot as a fallback when that key is absent.
It does not guess from hostname, property order, or a default Company label.
Malformed session responses fail collection rather than publish a snapshot.

Group evidence uses the lowercase property name as its external namespace
(for example, `customproperty1`) and the trimmed customer value as its external
ID and display name. Session identity remains `access-session/SessionID`.
The existing client resolver matches group names through its normal recorded
mapping, alias, and normalized-name workflow. Ambiguous or unmatched groups
remain reviewable; connectors never create client mappings directly.
Changing a customer property's value changes that group's source identity;
review its mapping instead of treating it as a stable vendor organization ID.

Sessions without a customer value remain source evidence without an empty-name
org/container or group-based client mapping. The shared identity resolver may
still associate a session to a known Computer and inherit that Computer's client;
otherwise it remains unassigned. Shared instances cannot also be assigned to
one client. Duplicate-session hints are computed within each group, preserving
different customers' same-named hosts.

Configuration writes and collection against a new production instance remain
separate operational actions. Validate customer-field population, Ninja group
overlap, ambiguous groups, and source/Computer counts before enabling scheduled
collection. Keep credentials and raw customer payloads out of reports and tests.

## Restored shared instance — active, scheduled every four hours

Read-only inspection on 2026-10-28 confirmed that `https://support.amrose.it/`
responds successfully. Its published field labels identify Custom Property 1 as
Company, 2 as Site, 3 as Department, and 4 as Device Type. The Host page requires
login. The label confirms the Company field number, not that ScreenConnect's
session groups are keyed by this property. Actual session values and Ninja
organization-name overlap were verified with authenticated read-only
inspection; the separate container/group definitions remain unavailable.

The production ScreenConnect source instance is named **AMROSE ScreenConnect** and is
configured with no assigned client. Its current config is:

```json
{
  "platform": "ScreenConnect",
  "source_key": "sc_amrose",
  "source_name": "AMROSE ScreenConnect",
  "base_url": "https://support.amrose.it",
  "is_shared": true,
  "screenconnect_group_field": "CustomProperty1",
  "ext_guid_ref": "SC_AMROSE_EXT_GUID",
  "secret_key_ref": "SC_AMROSE_SECRET_KEY"
}
```

Those environment names are private runtime references for the AMROSE
connection; secret values are never stored in Operations. Both references were
confirmed present in the ingest runtime. The source instance and its
`internal-ingest` binding are enabled, and the user saved `interval:240`
(every four hours) from `/sources/`. The source creation and activation are
recorded in change history. The existing client-scoped ScreenConnect instance,
which uses a different base URL, was left unchanged. The first refresh run
`5e27a49b-db4a-45b5-b9aa-93baf9b5adc4` completed with 4,632 rows touched, zero
failed rows, and a complete snapshot of 4,507 sessions. Safe aggregate
observation metadata showed Company on 4,424 sessions and blank on 83; it
produced 125 nonempty Company groups, no empty-name groups, 97 groups with a
client, and 28 unassigned groups. Thus blank Company sessions remain evidence
without creating an empty-name container or group-based mapping. The dependent
identity resolver completed at 21:22 UTC, resolving 417 records. Platform
evaluation is stalled because its coalesced Ninja workflow also requires
Ninja enrichment → patches → patch classification. The Ninja-enrichment run
stopped before reporting a terminal result at 21:27 UTC, leaving those
dependent runs and evaluation stalled. Portainer logged a successful stack
deployment at 21:27, and Docker events show the Operations, ingest, and Jobs
containers were replaced around 21:27:32. The initiating actor/trigger is not
in retained logs. All are healthy now. Replay-safe recovery automatically
retried Ninja enrichment, which completed at 21:32 UTC. Its recovery patches
and patch classification completed at 21:33 UTC; platform evaluation completed
at 21:39:15 with 5,874 rows touched and no error. The original interrupted
chain remains stalled in history. The source refresh also logged an
opportunistic generic relationship-projection cardinality error and continued.
Company is verified as
populated customer metadata with substantial Ninja-name overlap; it is not
verified as the separate Host-page container membership. The response had no
explicit session-group-named field, and a direct `GetSessionGroups` call to the
RESTful API Manager endpoint returned HTTP 500 without definitions. Do not
reuse the client-specific credential pair against this instance. Each
scheduled refresh uses the normal Jobs workflow, including identity resolution
and platform evaluation.
