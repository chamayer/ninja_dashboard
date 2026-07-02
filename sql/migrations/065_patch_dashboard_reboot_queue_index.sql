-- Speed up the Command Center "Patches Installed Awaiting Reboot" card.
-- The card starts from reboot-needed devices, then looks up installed
-- patch outcomes for each device.

CREATE INDEX IF NOT EXISTS latest_install_outcome_device_installed_idx
ON ninja_patches.latest_install_outcome (device_id, installed_at DESC)
WHERE status = 'INSTALLED'
  AND installed_at IS NOT NULL;
