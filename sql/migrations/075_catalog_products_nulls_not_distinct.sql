-- =============================================================================
-- 075_catalog_products_nulls_not_distinct.sql
-- Fix a defect in 074: products with no publisher would duplicate.
--
-- `UNIQUE (publisher_id, canonical_name)` does not constrain rows where
-- `publisher_id` is NULL, because PostgreSQL treats NULLs as distinct in a
-- unique index by default. 074 deliberately allows a NULL publisher -- 4 of
-- 484,636 installations carry none, and a title with an unknown vendor is
-- still a real product -- so the projector's ON CONFLICT would silently miss
-- them and insert a fresh row on every run.
--
-- Small blast radius today (4 installations), unbounded later: every
-- publisher the alias table has not yet learned arrives unnormalized, and any
-- future source reporting titles without a vendor lands here.
--
-- PostgreSQL 16 is deployed, so NULLS NOT DISTINCT is available and states the
-- intent directly rather than encoding it as COALESCE(publisher_id, -1).
-- =============================================================================

ALTER TABLE catalog.products
    DROP CONSTRAINT IF EXISTS uq_catalog_products_publisher_name;

ALTER TABLE catalog.products
    ADD CONSTRAINT uq_catalog_products_publisher_name
    UNIQUE NULLS NOT DISTINCT (publisher_id, canonical_name);
