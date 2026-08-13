-- 085: resumable cursor for the one-time CPE dictionary backfill.
--
-- `intel.cpes` holds 169,951 of NVD's 1,799,756 CPEs -- 9.4%. Not a bug in the
-- fetch: cpe_dict has only ever pulled *deltas*, `lastModStartDate` with a
-- 120-day first-run lookback, so any CPE whose record has not been touched
-- recently was never fetched at all. Its last run reported "Upserted 0 CPE
-- entries" -- fully caught up on a window that excludes most of the corpus.
--
-- The consequence is measured: the matcher can only match titles whose CPEs we
-- hold, and CVE coverage is 507 of 21,395 catalog titles.
--
-- A backfill pages the full index by startIndex with no date filter. With the
-- configured NVD API key that is ~0.65s/request, so 360 pages of 5,000 is about
-- four minutes and should finish in one cycle. The cursor exists so an
-- interrupted or rate-limited run resumes instead of restarting, and so the
-- state is inspectable rather than inferred.
--
-- One-time: once completed_at is set the connector returns to delta pulls and
-- never backfills again.

CREATE TABLE IF NOT EXISTS intel.cpe_backfill_state (
    id              boolean PRIMARY KEY DEFAULT true,
    next_index      bigint      NOT NULL DEFAULT 0,
    total_results   bigint      NOT NULL DEFAULT 0,
    rows_written    bigint      NOT NULL DEFAULT 0,
    started_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    -- Singleton: one backfill, one cursor.
    CONSTRAINT ck_cpe_backfill_singleton CHECK (id)
);

COMMENT ON TABLE intel.cpe_backfill_state IS
    'Resumable cursor for the one-time full CPE dictionary pull. While '
    'completed_at IS NULL the connector pages the full index by startIndex; '
    'once set it returns to normal lastModified delta pulls.';

COMMENT ON COLUMN intel.cpe_backfill_state.started_at IS
    'When the backfill began. Used as the delta baseline once it completes, '
    'because intel.cpes.updated_at records when *we* wrote a row, not when NVD '
    'modified it -- so it cannot tell us which records changed while the '
    'backfill was running.';

INSERT INTO intel.cpe_backfill_state (id) VALUES (true)
ON CONFLICT (id) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON intel.cpe_backfill_state TO ninja_ingest;
GRANT SELECT ON intel.cpe_backfill_state
    TO operations_app, operations_readonly, metabase_ro;
REVOKE DELETE, TRUNCATE ON intel.cpe_backfill_state
    FROM operations_app, operations_readonly, metabase_ro, ninja_ingest;
