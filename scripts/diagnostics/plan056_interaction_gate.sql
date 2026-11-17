-- Metadata only. Stop before sampling without full visibility and natural work.
SELECT jsonb_build_object('section','gate','utc',clock_timestamp(),
 'database_matches',current_database()='ninja',
 'full_stats',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
              OR pg_has_role(current_user,'pg_read_all_stats','MEMBER'),
 'read_only',current_setting('transaction_read_only')='on');
SELECT current_database()='ninja'
 AND current_setting('transaction_read_only')='on'
 AND ((SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
      OR pg_has_role(current_user,'pg_read_all_stats','MEMBER')) AS permitted
\gset
\if :permitted
\else
SELECT 1/0; -- Fail closed; no role fallback or grant.
\endif
SELECT EXISTS(SELECT 1 FROM operations.operator_job_runs
 WHERE tenant_id=1 AND status='running'
 AND job_key IN ('source-refresh','resolver','platform-evaluate',
                 'software-classify-only','software-classify-full',
                 'intel-matcher','source-record-assess','computer-client-ownership',
                 'computer-client-ownership-sweep')) AS natural_work
\gset
\if :natural_work
\else
SELECT 1/0; -- No idle baseline, forced Job or retry.
\endif
