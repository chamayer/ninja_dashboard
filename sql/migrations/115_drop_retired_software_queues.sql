-- 115: drop the retired per-client and on-demand software queues.
--
-- The software inventory rebuild (ADR 0029, release 0.127.0) replaced the
-- per-client queue with the daily full check and the on-demand queue with an
-- operator refresh that queues the computer in software_activity_queue.
-- Nothing reads or writes either table since then: the per-client queue never
-- completed an entry (78 pending rows), the on-demand queue held two rows from
-- 2026-07-08. Both were exported before this migration
-- (ninja_core.software_*_queue.2026-10-13.csv, kept locally). No constraint or
-- view depends on them. Their job_domain_attempts history (domain kinds
-- software.scheduled and software.demand) is kept.

DROP TABLE IF EXISTS ninja_core.software_scheduled_queue;
DROP TABLE IF EXISTS ninja_core.software_demand_queue;

DELETE FROM operations.queue_registry
 WHERE queue_key IN ('software.scheduled', 'software.demand');
