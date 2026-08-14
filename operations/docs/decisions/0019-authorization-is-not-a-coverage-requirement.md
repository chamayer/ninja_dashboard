# ADR-0019: Authorization is not a coverage requirement

- Status: accepted
- Date: 2026-08-14
- Supersedes: nothing
- Amends: ADR-0018 (software capability recognition), Contract 3

## Context

ADR-0018 defined `permitted` as:

> product mapped to a platform required by this client, OR an applicable
> approve decision

That made authorization a consequence of coverage policy. `operations.coverage_requirements`
and `operations.requirement_profile_items` state what a client **must** run and
drive `missing_required_platform`; the classifier then reused those same rows,
through `_load_sanctioned_product_identities`, to decide what a client is
**allowed** to run.

Measured 2026-08-13, with the capability gates off:

- ScreenConnect appears in exactly one requirement profile (UTA).
- The global fallback requires only LogMeIn, Ninja and SentinelOne.
- 70 of 76 clients have no requirement profile at all.
- The MSP's own ScreenConnect instance (`da1317176ae8a62a`, 3,012 devices,
  71 clients) was therefore not permitted anywhere, and would have raised
  `unauthorized_remote_access` on 3,007 devices across 70 clients.

The only available remedy was to add ScreenConnect to the coverage
requirements. That would have silenced the findings *and* asserted that every
client must run ScreenConnect, raising `missing_required_platform` at the five
clients that do not. The model could not express "allowed but not mandatory",
so populating `platform_product_map` correctly was not sufficient: the product
identity was right and the authorization question still had no home.

## Decision

Authorization becomes its own relation, `operations.product_authorizations`
(raw SQL migration 099, Django state-only 0139).

- **Required stays strictly coverage.** `coverage_requirements` and
  `requirement_profile_items` are unchanged, and
  `_load_sanctioned_product_identities` keeps its existing query and meaning.
- **Permitted is strictly authorization**, keyed on `product_uuid` and
  `capability` rather than on a platform, because being allowed is a property
  of the product. `platform_product_map` keeps its single job of platform to
  product identity.
- **Two tiers.** `client_id IS NULL` is the global tier; a client UUID scopes
  the row to one client. Device-level exceptions already exist in
  `software_decisions` and are not duplicated here.
- **`polarity` is `NOT NULL` with no default** in both migration runners.
  Permit and deny are opposite decisions, and an authorization must state which
  one it is; a default would let an incomplete write silently become a permit.

### Precedence

Evaluated per `(product, capability, client)` in `_permitted()`, first match
wins:

| # | rule | outcome |
| --- | --- | --- |
| 1 | client-scoped deny | not permitted, terminal |
| 2 | client-scoped permit | permitted |
| 3 | global deny | not permitted, terminal |
| 4 | global permit | permitted |
| 5 | product mapped to a platform the client requires | permitted |
| 6 | no match | not permitted, emits `unauthorized_<capability>` |

Deny precedes permit at each tier so a client can be excluded from something
permitted fleet-wide, which a single boolean cannot express. Client precedes
global because the narrower row is a decision about that client, not an
oversight. Rule 5 ranks last and unchanged, so no coverage behavior shifts.

`_permitted()` returns the deciding rule with the verdict, and the finding
records it as `not_permitted_basis`, so why something was not permitted is
stored rather than re-derived.

## Consequences

- A product can be authorized without being mandated. A single global permit
  for the two `da1317176ae8a62a` products would clear roughly 3,007 device
  findings while asserting nothing about who must run ScreenConnect.
- An explicit deny outranks the required-platform mapping, because an operator
  decision outranks an inference from coverage policy.
- Withdrawal, not deletion, is the retirement path. `DELETE` and `TRUNCATE` are
  revoked from every runtime role; `withdrawn_at` is paired with a non-empty
  `withdrawn_reason` by CHECK, and the unique indexes ignore withdrawn rows so
  re-authorizing inserts a fresh row and leaves the gap visible.
- Authorization carries its own permission, `authorize_software_product`,
  separate from `curate_software_capability`. What a product *is* and whether
  it is *allowed here* are different decisions and do not share a grant.
- The table is added to the classifier's fail-closed schema probe. Absent, the
  classifier reports capability-not-ready rather than running enforcement with
  nothing able to permit.
- Column parity between the two migration runners is asserted by
  `test_product_authorization_parity`. ADR-0012's note that nothing enforces
  this parity no longer holds for this table.

## Alternatives considered

- **A scope column on `platform_product_map`.** Rejected: it is keyed by
  `agent_id`, so client-scoped authorization would need duplicate identity rows
  per client and would re-couple authorization to platforms, which is the
  coupling being removed.
- **Reusing `software_decisions` approve at client scope.** Rejected: it is
  keyed on `canonical_name` and `publisher`, reintroducing name-based identity
  immediately after the product map replaced it, and it conflates trust with
  authorization.
- **Adding ScreenConnect to `coverage_requirements`.** Rejected: this is the
  overload the ADR exists to prevent, and it would raise
  `missing_required_platform` at five clients.

## Open

Enforcement remains off. Enabling it still requires endpoint-security
recognition (0 alertable `endpoint_security` products as of 2026-08-14) and an
operator decision on the seven foreign ScreenConnect instance GUIDs covering
2,218 devices.
