# Metabase retirement archive and restoration

This directory is the local rollback archive for the retired Metabase service.
It is deliberately excluded from Git and Docker build contexts. Only this
runbook is tracked.

## Required archive contents

Before removing the live service, create these local files in this directory:

| Artifact | Purpose |
|---|---|
| `dashboards/` | JSON export of the active dashboards. It is a convenient inspection copy; the application dump below is the authority for all dashboard metadata, including already-archived dashboards. |
| `metabase-application.dump` | Custom-format `pg_dump` of the exact Postgres database used by Metabase for its application metadata. This is the complete recovery copy for active and archived Metabase content. |
| `metabase-data.tar.gz` | Archive of the mounted `metabase-data` volume. Keep it even when Metabase is configured to use Postgres metadata. |
| `manifest.sha256` | SHA-256 hash for every archived file. |
| `archive-details.txt` | Archive time, Metabase version, dashboard identifiers/names, application database name, Docker volume identifier, export command version, and restore prerequisites. Never include passwords, tokens, connection strings, or customer data. |

The database name and volume identifier must be measured from the running
production service at archive time. Do not infer either from this repository.

## Archive procedure

1. Stop new Metabase changes for the duration of the archive.
2. Export the active dashboard definitions through the Metabase API. The
   application-database dump remains the full recovery authority for active
   and archived content.
3. Create a custom-format dump of the Metabase *application* database and a
   tar archive of the exact mounted volume. Transfer both to this local
   directory over the approved secure administration path.
4. Create `archive-details.txt` and `manifest.sha256` locally. Verify each
   hash before changing the live service.
5. Confirm that the archive directory is ignored by Git:

   ```powershell
   git check-ignore -v archive/metabase/metabase-application.dump
   ```

6. Only after the local archive is verified may the dashboards be archived and
   the live Metabase service, port, and volume be removed through the approved
   GitOps cutover.

## Restoration procedure

Restoration is a separate production change and requires explicit approval.

1. Confirm the target stack version is compatible with the archived Metabase
   version recorded in `archive-details.txt`.
2. Restore the application database from `metabase-application.dump` into a
   dedicated Metabase application database; do not overwrite Operations or
   ingest databases.
3. Create a Docker volume and restore `metabase-data.tar.gz` into it, retaining
   original ownership where the image requires it.
4. Temporarily restore the reviewed Metabase Compose service using the recorded
   image version, database identity, and volume mount. Supply credentials only
   from the approved secret store.
5. Start it without bootstrap provisioning. Verify the archived dashboards and
   definitions are present, then decide whether to unarchive only the specific
   dashboard needed.
6. Remove the temporary restoration service after the investigation unless a
   separately approved rollback reactivates it.

Never run a bootstrap against a restored archive: it can overwrite
operator-authored dashboard metadata.
