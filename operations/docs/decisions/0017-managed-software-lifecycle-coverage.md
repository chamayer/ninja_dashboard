# ADR-0017: managed lifecycle-family coverage is global and deterministic

**Status:** accepted 2026-08-11

## Context

Lifecycle coverage must focus on software that has an independently supported
release lifecycle. A broad corpus-to-catalogue candidate matcher is both slow
and unsafe: unrelated title substrings can acquire a precise, incorrect EOL
date. An operator-maintained mapping queue also conflicts with the requirement
that routine lifecycle coverage needs no manual upkeep.

## Decision

Use the global, migration-seeded `intel.eol_managed_product_rules` table for a
small set of verified, high-risk product families. Rules use narrow catalogue
title patterns, optional publisher gates, and optional version/cycle selectors;
they never contain lifecycle dates or build maps. The existing EOL projector
remains the single writer of `catalog.software_versions.eol_date` and
`eol_source`, resolving dates only from the refreshed endoflife.date corpus.

The historical `operations.eol_product_map` remains readable for compatibility
with its verified rows but is not writable by the Operations application. The
candidate materialized view is retired. The generic matcher in migration 086
is not part of this lifecycle path.

## Consequences

Known families are refreshed automatically when either the corpus or software
catalogue changes. Ambiguous or unrecognized titles remain unmapped instead of
being guessed. Microsoft 365 channel currency, Adobe Acrobat/Reader, and
Visual C++ redistributables remain separate concerns: they cannot safely be
claimed by these rules without a trustworthy lifecycle source or distinct
evidence model.
