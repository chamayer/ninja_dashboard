-- 100: vetted endpoint_security rules -- AV recognition.
--
-- Before this migration `endpoint_security` had 65 candidate products and
-- ZERO alertable ones, so `unauthorized_av` could not fire at all and recall
-- was not claimable. Migration 094 deliberately seeded no vetted AV rule,
-- recording that `sentinel` is a common word and that promotion should wait
-- for measurement. This is that measurement.
--
-- `vetted_rule` is ALERTABLE, so every row is an individual judgement. Each
-- pattern below was dry-run against the whole product catalog on 2026-08-14,
-- and the rules together claim 36 products / 4,233 devices / 73 clients with
-- no false positive in the result.
--
-- Two measured traps shaped these patterns:
--
--   `sentinel agent%` and not `sentinel%`. SafeNet, Thales and Gemalto ship
--   `sentinel protection installer`, `sentinel rms license manager`,
--   `sentinel runtime` and `sentinel system driver installer` -- software
--   licensing components sharing only the word. Verified: the anchored
--   pattern claims the three SentinelOne products and none of theirs.
--
--   `malwarebytes version%` and not `malwarebytes%`. Malwarebytes Privacy is
--   a VPN, and a blanket vendor pattern claimed it as endpoint security.

INSERT INTO catalog.capability_rule
    (rule_key, capability, title_pattern, publisher_pattern, source_key,
     priority, notes)
VALUES
    -- The sanctioned endpoint platform. Largest single title in the fleet.
    ('vet-sentinelone-agent', 'endpoint_security', 'sentinel agent%', '', 'vetted_rule', 100,
     'SentinelOne EDR agent. Measured 2026-08-14: 4,193 devices / 73 clients '
     || 'across three product identities (publishers SentinelOne and Sentinel '
     || 'Labs, Inc.). Anchored on "sentinel agent" rather than "sentinel" '
     || 'because SafeNet/Thales licensing components share the first word; '
     || 'verified to claim none of them.'),

    -- CrowdStrike Falcon. The sensor is the protection engine; the platform
    -- package carries it.
    ('vet-crowdstrike-sensor', 'endpoint_security', 'crowdstrike windows sensor%', '', 'vetted_rule', 100,
     'CrowdStrike Falcon sensor. Measured 2026-08-14: 78 devices / 3 clients.'),
    ('vet-crowdstrike-platform', 'endpoint_security', 'crowdstrike sensor platform%', '', 'vetted_rule', 100,
     'CrowdStrike Falcon sensor platform package. Measured 2026-08-14: 80 '
     || 'devices / 3 clients.'),

    ('vet-symantec-endpoint', 'endpoint_security', 'symantec endpoint protection%', '', 'vetted_rule', 100,
     'Symantec Endpoint Protection, publisher Broadcom / Symantec. Measured '
     || '2026-08-14: 54 devices / 12 clients. The title names the product, not '
     || 'the vendor, so the Broadcom driver packages are not reached.'),

    ('vet-kaspersky-endpoint', 'endpoint_security', 'kaspersky endpoint security%', '', 'vetted_rule', 100,
     'Kaspersky Endpoint Security for Windows. Measured 2026-08-14: 16 devices '
     || 'across two versioned identities. Excludes Kaspersky Security Center '
     || 'Network Agent, which is a management agent rather than the engine.'),

    ('vet-trendmicro-officescan', 'endpoint_security', 'trend micro officescan%', '', 'vetted_rule', 100,
     'Trend Micro OfficeScan client. Measured 2026-08-14: 2 devices / 1 client.'),

    -- Malwarebytes ships the engine under a version-suffixed title, and its
    -- VPN under the same vendor name -- hence three narrow patterns rather
    -- than one vendor pattern.
    ('vet-malwarebytes-version', 'endpoint_security', 'malwarebytes version%', '', 'vetted_rule', 100,
     'Malwarebytes anti-malware engine, titled with its version. Measured '
     || '2026-08-14: 12 product identities / 43 devices.'),
    ('vet-malwarebytes-antimalware', 'endpoint_security', 'malwarebytes anti-malware%', '', 'vetted_rule', 100,
     'Older Malwarebytes Anti-Malware naming. Measured 2026-08-14: 2 devices.'),
    ('vet-malwarebytes-package', 'endpoint_security', 'malwarebytes.antimalware%', '', 'vetted_rule', 100,
     'Malwarebytes store-package identity. Measured 2026-08-14: 5 devices / 4 clients.'),
    ('vet-threatdown', 'endpoint_security', 'threatdown%', '', 'vetted_rule', 100,
     'ThreatDown endpoint agent, the Malwarebytes EDR product. Measured '
     || '2026-08-14: 3 product identities / 17 devices.'),

    -- Vendors absent from the 094 publisher seed, so nothing recognized these
    -- at all. Small footprints, but an unsanctioned AV at a client is exactly
    -- what unauthorized_av exists to surface.
    ('vet-huntress-agent', 'endpoint_security', 'huntress agent%', '', 'vetted_rule', 100,
     'Huntress managed EDR agent. Measured 2026-08-14: 7 devices / 1 client.'),
    ('vet-webroot-secureanywhere', 'endpoint_security', 'webroot secureanywhere%', '', 'vetted_rule', 100,
     'Webroot SecureAnywhere antivirus. Measured 2026-08-14: 5 devices / 1 client.'),
    ('vet-avast-antivirus', 'endpoint_security', 'avast antivirus%', '', 'vetted_rule', 100,
     'Avast Antivirus. Measured 2026-08-14: 2 devices. Anchored on the product '
     || 'name: Avast also ships SecureLine VPN, a browser and an update helper.'),
    ('vet-avast-business', 'endpoint_security', 'avast business%', '', 'vetted_rule', 100,
     'Avast Business Antivirus. Measured 2026-08-14: 1 device.'),
    ('vet-avg-internet-security', 'endpoint_security', 'avg internet security%', '', 'vetted_rule', 100,
     'AVG Internet Security. Measured 2026-08-14: 1 device. AVG TuneUp, Secure '
     || 'Browser and Web TuneUp are deliberately not reached.'),
    ('vet-avg-antivirus', 'endpoint_security', 'avg antivirus%', '', 'vetted_rule', 100,
     'AVG AntiVirus. Measured 2026-08-14: 1 device.'),
    ('vet-panda-devices', 'endpoint_security', 'panda devices agent%', '', 'vetted_rule', 100,
     'Panda (WatchGuard) endpoint agent. Measured 2026-08-14: 1 device.'),
    ('vet-panda-universal', 'endpoint_security', 'panda universal agent%', '', 'vetted_rule', 100,
     'Panda (WatchGuard) universal endpoint agent. Measured 2026-08-14: 1 device.')
ON CONFLICT (rule_key) DO NOTHING;

-- Deliberately NOT promoted to vetted_rule, so the omissions are decisions
-- rather than oversights. All remain publisher_rule candidates.
--
--   crowdstrike device control / firmware analysis -- Falcon platform modules
--       rather than the protection engine. Real endpoint security software,
--       but promoting a module would assert engine presence on a device that
--       may carry only the module.
--   webadvisor by mcafee, mcafee true key, mcafee safe connect -- a browser
--       extension, a password manager and a VPN. Vendor is not capability.
--   mcafee security scan plus, norton security scan -- on-demand scanners, not
--       resident protection.
--   symantec vip access, liveupdate, backup exec remote agent -- multi-factor,
--       an updater and backup software.
--   kaspersky security center network agent -- management plane.
--   sophos ssl vpn client -- a VPN.
--   sentinelone extensions, sentinelappvulnerability, sentinel_updater -- real
--       SentinelOne components, but they accompany the agent that
--       vet-sentinelone-agent already claims; alerting on them separately
--       would double-count one installation.
--   microsoft defender -- installed presence does not mean the active
--       protection engine, which is the multi_av_conflict problem and stays
--       gated pending a real Windows Security Center signal.
--   avast/avg update helpers, secure browsers, tuneup, secureline, avira
--       fallback updater -- utilities and updaters from security vendors.
--   eset -- present only as `esetcontextmenu`, a sparse shell-extension
--       package. The engine itself is not in the fleet, and `eset` as a
--       substring matches `remotesetup` and `sfpreset`, which is why
--       substring sanctioning was removed in the first place.
