# 0018 — Software capability recognition

Status: Accepted
Date: 2026-08-12

## Context

The former software category field attempted to answer too many questions at
once: what a product does, whether a platform requires it, and whether an
operator trusts it. Only seven of 21,995 observed titles had categories, while
the category labels were the sole trigger for unauthorized AV, RMM, and remote
access findings. The resulting low counts described a blind sensor, not a
clean fleet.

Name containment made the existing sanctioned check unsafe in both directions:
the two remote-access platform names matched 99 titles and 11,024 installation
rows. A product identity must not be inferred from either side containing the
other's display name.

## Decision

Capability is global product evidence, separate from both policy and trust.

| Question | Authority | Storage |
| --- | --- | --- |
| What is this product capable of? | Evidence plus curator confirmation | `catalog.capability_*` assertions and effective view |
| Is it required/allowed for this client? | Requirement profile and product identity mapping | `operations.platform_product_map` |
| Has an operator approved the software? | Tenant-scoped software decision | `operations.software_decisions` |

Machine assertions are positive-only. Their source is an immutable registry
with `may_alert` derived from source authority; an evidence producer cannot
promote a community tag into an alert. Operator assertions live in a separate
table and can persist an authoritative negative. Effective precedence is:
operator negative, operator positive, alertable machine assertion, candidate
machine assertion, then unknown (no row).

Only an alertable effective capability can produce `unauthorized_*`. Policy
exemption is an exact catalog product UUID mapped to the required platform for
the applicable client. A platform may map to many product identities, because
agents commonly install a tray program, updater, and uninstaller as separate
products. Display-name containment is removed from enforcement.

Candidate sources produce review evidence only. A platform curator, not an
ordinary tenant operator, may confirm or reject global capability truth; every
such action writes an operator assertion and an audit event. Trust decisions do
not answer capability-review questions.

LOLRMM is a vetted capability corpus but not a local identity source. It may
produce alertable evidence only for a one-to-one exact normalized local product
name. Corpus or local-name collisions become candidate evidence. A failed,
empty, or partially parsed corpus never withdraws prior assertions.

`multi_av_conflict` remains disabled. Installed packages do not prove active
protection; it needs Windows Security Center or must be renamed to describe
package inventory.

## Consequences

- The established public finding name `unauthorized_av` remains; the capability
  vocabulary calls it `endpoint_security`, with the finding mapping stored as
  data on `catalog.capability`.
- Unauthorized findings are device-scoped because policy is client-specific.
  Existing product-scoped rows are closed and regenerate at the correct scope
  when enforcement is enabled.
- Capability enforcement and candidate review default off until production
  product maps and shadow-mode precision/recall evidence exist. This is a
  fail-closed operational gate, not a fallback to substring matching.
- `PublisherCategory` is retired from capability logic. Only its AV/EDR, RMM,
  and remote-access tokens migrate as candidate publisher rules; `management`
  and other generic taxonomy labels do not infer capability.
