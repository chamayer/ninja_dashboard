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

## Restored shared instance — connection draft

Read-only inspection on 2026-10-28 confirmed that `https://support.amrose.it/`
responds successfully. Its published field labels identify Custom Property 1 as
Company, 2 as Site, 3 as Department, and 4 as Device Type. The Host page requires
login. The label confirms the Company field number, not that ScreenConnect's
session groups are keyed by this property. Actual session values, group
definitions, and Ninja name overlap still require authenticated read-only
verification before activation.

Proposed config for a **new, initially disabled** ScreenConnect source instance
with no assigned client:

```json
{
  "platform": "ScreenConnect",
  "source_key": "sc_amrose",
  "source_name": "ScreenConnect shared",
  "base_url": "https://support.amrose.it",
  "is_shared": true,
  "screenconnect_group_field": "CustomProperty1",
  "ext_guid_ref": "SC_AMROSE_EXT_GUID",
  "secret_key_ref": "SC_AMROSE_SECRET_KEY"
}
```

Those environment names are the private runtime references for the AMROSE
connection; secret values are never stored here.
Read-only inspection through the private ingest-host profile found one enabled
ScreenConnect instance assigned to a client, with a different base URL, and no
separate shared instance for this URL. The user subsequently added the proposed
AMROSE GUID/key runtime references and corrected the extension ID. Read-only
retrieval returned 4,511 Access sessions (4,506 active hosts). Company
(`CustomProperty1`) was populated on 4,422 active hosts; 83 of its 125 distinct values matched
Ninja organization names case-insensitively, and 85 matched after
punctuation-insensitive normalization. The response had no explicit
session-group-named field. A direct `GetSessionGroups` call to the RESTful API
Manager endpoint returned HTTP 500 without definitions. Company is verified as
populated customer metadata with substantial Ninja-name overlap; it is not
verified as the separate Host-page container membership. Review unmatched
Company values and obtain a supported read path for group definitions/membership
before enabling collection. Do not reuse the client-specific credential pair
against this instance. Source/binding creation and collection activation remain
separate production operations.
