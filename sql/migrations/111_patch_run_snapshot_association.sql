-- Associate patch facts with the collector snapshot used for the run.
ALTER TABLE ninja_core.run_log
    ADD COLUMN IF NOT EXISTS snapshot_at timestamptz;
