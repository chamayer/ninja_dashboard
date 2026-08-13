-- 098: resolve the nine capability conflicts measured in shadow mode.
--
-- A conflict here means one product carrying two different capabilities at
-- once, so a single installation would raise both unauthorized_rmm and
-- unauthorized_remote_access. Nine products were affected, from two distinct
-- root causes -- not nine independent judgements.

-- ---------------------------------------------------------------------------
-- Cause 1 (seven products): the LOLRMM Category was mapped straight onto our
-- capability at the alertable tier.
--
-- LOLRMM labels TeamViewer, ScreenConnect, AnyDesk, LogMeIn and GoToMyPC
-- "RMM", while the vetted rules seeded in 094 deliberately call those
-- remote_access. Both tiers alert, so both fired.
--
-- The corpus is "tools abused for unattended remote access", which is what
-- our remote_access means; the RMM/RAT split describes vendor legitimacy, not
-- capability. `rmm` means full endpoint management -- patching, scripting,
-- monitoring -- which a name match against this corpus cannot establish.
-- `ingest/intel/lolrmm.py` now assigns remote_access unconditionally.
--
-- The connector's own reconcile would withdraw these rows on its next run,
-- but under the reason "no longer matched by complete LOLRMM corpus", which
-- is false: the corpus still matches the product. Withdraw them here so the
-- recorded cause is the real one.
UPDATE catalog.capability_assertion_machine
   SET withdrawn_at = now(),
       withdrawn_reason = 'lolrmm Category no longer mapped to rmm (098): the '
                       || 'corpus evidences remote_access, and rmm requires '
                       || 'management capability a name match cannot show'
 WHERE withdrawn_at IS NULL
   AND source_key IN ('lolrmm', 'lolrmm_candidate')
   AND capability = 'rmm';

-- ---------------------------------------------------------------------------
-- Cause 2 (two products): 094 seeded two ConnectWise publisher rules with the
-- identical `ConnectWise%` publisher pattern and no title pattern, so every
-- ConnectWise product was asserted both rmm and remote_access. ConnectWise
-- ships both an RMM (Automate) and a remote access tool (ScreenConnect /
-- Control), and a publisher-wide rule cannot tell them apart.
--
-- Candidate tier, so this never alerted -- but it is wrong at the source and
-- would have become alertable had either rule ever been promoted.
--
-- Give each rule the title that identifies its product line. Both remain
-- publisher_rule, so both remain candidate-only: this narrows an over-broad
-- rule, it does not grant new authority.
UPDATE catalog.capability_rule
   SET title_pattern = 'connectwise automate%',
       notes = notes || ' | 098: narrowed from a publisher-wide match, which '
                     || 'asserted rmm on ConnectWise remote access products too'
 WHERE rule_key = 'pub-connectwise-rmm';

UPDATE catalog.capability_rule
   SET title_pattern = 'screenconnect%',
       notes = notes || ' | 098: narrowed from a publisher-wide match, which '
                     || 'asserted remote_access on ConnectWise Automate too. '
                     || 'The ConnectWise Control rebrand is carried by the '
                     || 'connectwisecontrol-% title, covered by its own rule'
 WHERE rule_key = 'pub-connectwise-ra';

-- ConnectWise Control is ScreenConnect under its former name and appears in
-- the fleet as `connectwisecontrol-<instance guid>`. The narrowed rule above
-- no longer reaches it, so state it explicitly rather than widening that
-- pattern back out.
INSERT INTO catalog.capability_rule
    (rule_key, capability, title_pattern, publisher_pattern, source_key,
     priority, notes)
VALUES
    ('pub-connectwise-control', 'remote_access', 'connectwisecontrol-%',
     'ConnectWise%', 'publisher_rule', 200,
     'ConnectWise Control, the former name of ScreenConnect. Split out in 098 '
     || 'when the publisher-wide ConnectWise rules were narrowed.')
ON CONFLICT (rule_key) DO NOTHING;

-- The stale publisher_rule assertions are deliberately NOT withdrawn here.
-- The capability projector owns vetted_rule and publisher_rule: it rebuilds
-- the desired set from this table on every run and withdraws whatever no
-- longer matches, under 'no longer matched by publisher_rule rules', which is
-- exactly what happened. Withdrawing them by hand would also have to reach
-- ScreenConnect products, whose canonical_name does not begin with
-- "connectwise" even though the ConnectWise publisher rules matched them --
-- an easy row set to get wrong, and the projector already has it right.
--
-- This is the opposite of the LOLRMM case above, where the corpus still
-- matches the product and only our reading of it changed, so the connector's
-- own reason would have been false.
