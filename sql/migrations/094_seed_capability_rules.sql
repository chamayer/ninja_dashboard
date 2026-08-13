-- 094: seed capability rules.
--
-- Two tiers, and the difference matters more than the content.
--
-- `publisher_rule` is CANDIDATE-ONLY. It can never raise an unauthorized
-- finding (catalog.capability_source.may_alert is FALSE and CHECK-derived from
-- the authority class). A publisher rule says "this vendor makes security
-- software", which is not the same as "this product is an AV engine" -- the
-- same publisher ships installers, consoles, browser extensions and uninstall
-- stubs.
--
-- `vetted_rule` is ALERTABLE, so every row below is an individual judgement
-- with its evidence in `notes`. None is here because it looked plausible.
--
-- Anchored patterns only; the table's CHECK rejects a leading % or _. A
-- vetted_rule additionally requires a title pattern, so a publisher-only rule
-- cannot become alertable across a vendor's whole catalog.

-- ---------------------------------------------------------------------------
-- publisher_rule: migrated from operations.publisher_categories (seeded by
-- Operations migration 0087), taking ONLY the capability-relevant tokens:
--
--     av, edr      -> endpoint_security
--     rmm          -> rmm
--     remote-access-> remote_access
--
-- `management` is deliberately NOT mapped. It is not evidence of RMM: Datto
-- carries ["management", "backup"] and is a backup vendor, so inferring rmm
-- from management would assert a capability nobody claimed. Every other token
-- in that taxonomy -- system, browser, productivity, media, development,
-- runtime, virtualization, storage, networking, database, engineering,
-- utility, security, driver, communication, backup -- is ignored here: this is
-- capability recognition, not taxonomy.
-- ---------------------------------------------------------------------------
INSERT INTO catalog.capability_rule
    (rule_key, capability, title_pattern, publisher_pattern, source_key,
     priority, notes)
VALUES
    -- av / edr -> endpoint_security
    ('pub-symantec',    'endpoint_security', '', 'Broadcom%',      'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-kaspersky',   'endpoint_security', '', 'Kaspersky%',     'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-mcafee',      'endpoint_security', '', 'McAfee%',        'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-sentinelone', 'endpoint_security', '', 'SentinelOne%',   'publisher_rule', 200, 'publisher_categories: edr'),
    ('pub-trendmicro',  'endpoint_security', '', 'Trend Micro%',   'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-bitdefender', 'endpoint_security', '', 'Bitdefender%',   'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-crowdstrike', 'endpoint_security', '', 'CrowdStrike%',   'publisher_rule', 200, 'publisher_categories: edr'),
    ('pub-sophos',      'endpoint_security', '', 'Sophos%',        'publisher_rule', 200, 'publisher_categories: av'),
    ('pub-malwarebytes','endpoint_security', '', 'Malwarebytes%',  'publisher_rule', 200, 'publisher_categories: av'),
    -- rmm
    ('pub-ninjaone',    'rmm',           '', 'NinjaOne%',      'publisher_rule', 200, 'publisher_categories: rmm'),
    ('pub-connectwise-rmm', 'rmm',       '', 'ConnectWise%',   'publisher_rule', 200, 'publisher_categories: rmm'),
    -- remote-access
    ('pub-citrix',      'remote_access', '', 'Citrix%',        'publisher_rule', 200, 'publisher_categories: remote-access'),
    ('pub-logmein',     'remote_access', '', 'LogMeIn%',       'publisher_rule', 200, 'publisher_categories: remote-access'),
    ('pub-goto',        'remote_access', '', 'GoTo%',          'publisher_rule', 200, 'publisher_categories: remote-access (LogMeIn / GoTo)'),
    ('pub-connectwise-ra','remote_access','', 'ConnectWise%',  'publisher_rule', 200, 'publisher_categories: remote-access'),
    ('pub-teamviewer',  'remote_access', '', 'TeamViewer%',    'publisher_rule', 200, 'publisher_categories: remote-access'),
    ('pub-anydesk',     'remote_access', '', 'AnyDesk%',       'publisher_rule', 200, 'publisher_categories: remote-access'),
    ('pub-splashtop',   'remote_access', '', 'Splashtop%',     'publisher_rule', 200, 'publisher_categories: remote-access')
ON CONFLICT (rule_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- vetted_rule: ALERTABLE. Each row is an individual judgement.
--
-- Deliberately small. These are agent products whose title identifies one
-- specific piece of software rather than a family, measured present in the
-- fleet on 2026-08-12. Anything ambiguous stays a candidate until shadow mode
-- produces evidence for it -- a wrong vetted rule raises an unauthorized
-- finding against innocent software, which erodes trust faster than a missed
-- detection.
-- ---------------------------------------------------------------------------
INSERT INTO catalog.capability_rule
    (rule_key, capability, title_pattern, publisher_pattern, source_key,
     priority, notes)
VALUES
    ('vet-ninjarmmagent', 'rmm', 'ninjarmmagent%', '', 'vetted_rule', 100,
     'The NinjaOne RMM agent itself. Measured on 4,233 devices, the fleet''s '
     || 'largest title. The name identifies exactly one product.'),
    ('vet-screenconnect', 'remote_access', 'screenconnect%', '', 'vetted_rule', 100,
     'ConnectWise ScreenConnect / Control client. Anchored on the product '
     || 'name; the publisher varies across rebrands, so the title carries the '
     || 'identity.'),
    ('vet-anydesk', 'remote_access', 'anydesk%', '', 'vetted_rule', 100,
     'AnyDesk remote control. Chocolatey tags for this title measured '
     || '2026-08-12: remote, rdp, desktop, control, support.'),
    ('vet-teamviewer', 'remote_access', 'teamviewer%', '', 'vetted_rule', 100,
     'TeamViewer remote control. Title identifies one product family.'),
    ('vet-splashtop', 'remote_access', 'splashtop%', '', 'vetted_rule', 100,
     'Splashtop remote access.')
ON CONFLICT (rule_key) DO NOTHING;

-- Deliberately NOT seeded as vetted_rule, recorded so the omissions are
-- decisions rather than oversights:
--
--   'sentinel agent'  -- measured on 4,166 devices and almost certainly the
--                        SentinelOne EDR agent, but `sentinel` is a common
--                        word and the publisher rule already produces a
--                        candidate. Promote after shadow mode confirms the
--                        title on real installs.
--   'logmein%'        -- LogMeIn ships remote access AND unrelated products
--                        (Central, Rescue, Hamachi). Needs per-product review.
--   'microsoft defender%' -- installed presence does not mean the active
--                        protection engine; that is the multi_av_conflict
--                        problem, gated pending Windows Security Center.
--   'datto%'          -- backup vendor carrying a `management` token. Mapping
--                        management to rmm is exactly what this migration
--                        refuses to do.
