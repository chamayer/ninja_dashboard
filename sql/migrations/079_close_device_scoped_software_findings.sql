-- 079: retire the device-subject software findings that the re-subjecting
-- replaces, with the cause recorded on each row.
--
-- Seven of the nine software finding types move from subject_type='device' to
-- 'software_product' or 'software_version' (Django migration 0130 registers
-- which). Their condition keys change wholesale, because client and device
-- leave the key. Left alone, `_auto_resolve` would notice 134,484 keys missing
-- on the first run after deploy and mark them all resolved -- correct in
-- outcome, but it would look like 134,484 problems spontaneously fixed
-- themselves, and it sets neither `closed_at` nor any reason.
--
-- ADR-0012: nothing is lost without when and why. So the closure happens here,
-- explicitly, before the classifier next runs.
--
-- The type names are written out rather than read from `finding_types`
-- because `subject_scope` is set by the *Django* migration runner, which is a
-- separate system from this one with no ordering guarantee between them. This
-- is a one-time data operation over a fixed historical set, not a runtime
-- mapping, so naming them here does not put a domain mapping in code.

UPDATE operations.findings f
   SET status    = 'resolved',
       closed_at = COALESCE(f.closed_at, now()),
       finding_details = f.finding_details || jsonb_build_object(
           'resolution', jsonb_build_object(
               'reason', 'resubjected_to_software_scope',
               'detail', 'Superseded by a finding on the software title or '
                      || 'release. The condition was not remediated; only the '
                      || 'subject it is recorded against changed.',
               'previous_subject_type', f.subject_type,
               'previous_subject_id',   f.subject_id,
               'migration', '079',
               'closed_at', to_char(now() AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"')
           )
       )
  FROM operations.finding_types ft
 WHERE ft.id = f.finding_type_id
   AND ft.source_module = 'platform.software_findings'
   AND f.subject_type = 'device'
   AND f.status IN ('open', 'acknowledged')
   AND ft.name IN (
        'whitelist_suggestion',
        'suspicious_name',
        'unauthorized_av',
        'unauthorized_rmm',
        'unauthorized_remote_access',
        'known_malicious_hint',
        'vulnerable_software',
        'eol_runtime'
   );

-- rare_recent, install_path_suspicious and multi_av_conflict are deliberately
-- absent: they stay device-scoped, so their rows stay open and their condition
-- keys are unchanged.
