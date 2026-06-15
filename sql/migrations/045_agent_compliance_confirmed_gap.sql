-- Alerts should only fire on confirmed gaps, not Review-class
-- judgment calls. Findings get a `confirmed_gap` boolean set at
-- emission time:
--   * missing_required_platform → true when the device has online
--     presence on some platform OR the missing platform is observed
--     under the same hostname for another customer (the Fix-now
--     condition).
--   * stale_required_platform → false (always Review/Stale, never
--     auto-alert; goes to the daily Review digest).
--   * source_failure → true (operational, not subject to review).
--
-- Existing finding rows default to false. The next collection /
-- evaluate cycle re-emits findings with the correct flag.

ALTER TABLE ninja_agent_compliance.compliance_findings
    ADD COLUMN IF NOT EXISTS confirmed_gap boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS compliance_findings_confirmed_gap_idx
    ON ninja_agent_compliance.compliance_findings (run_id, status, confirmed_gap);
