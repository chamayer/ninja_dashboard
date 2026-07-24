"""Software safety intel ingest layer (ADR 0008).

Free-tier bulk connectors for vulnerability + OSINT feeds. Each
connector is a module exposing ``run_once(cur) -> int`` (returning rows
touched) and updating operations.intel_ingest_status with its result.

Enabled gates live on ingest.config.settings — every connector is
independently switchable so a broken feed can be turned off without
disturbing the rest.

Connectors:

  nvd            — NIST NVD v2 delta pull
  cpe_dict       — NIST CPE 2.3 dictionary
  cisa_kev       — CISA Known Exploited Vulnerabilities feed
  epss           — FIRST.org EPSS score CSV
  winget         — microsoft/winget-pkgs manifests
  chocolatey     — Chocolatey community feed
  otx            — AlienVault OTX pulses
  abusech        — abuse.ch MalwareBazaar + ThreatFox dump files

Matcher (canonical_name × CPE → operations.cve_match) lives in
ingest.intel.matcher and runs on its own cadence.

Composite safety scorer lives in operations.apps.core.safety and is a
read-side derivation only.
"""
