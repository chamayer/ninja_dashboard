"""Environment-driven configuration.

Loads /app/.env (bind-mounted from the host) into os.environ, then
parses required + optional settings via pydantic-settings. Fails loudly
on missing required values.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load /app/.env before pydantic-settings reads os.environ.
# Directory mount first, legacy single-file mount second. A single-file bind
# mount stays pinned to the inode present at container creation, so an
# atomic-save editor (write temp + rename) silently leaves the container
# reading the old file forever. Both paths are accepted so the compose and
# code halves of that change can deploy in either order.
for _env_path in (Path("/app/envdir/.env"), Path("/app/.env")):
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
        break


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    # ── Ninja API ────────────────────────────────────────────────────
    NINJA_BASE_URL: str
    NINJA_TOKEN_URL: str
    NINJA_CLIENT_ID: str
    NINJA_CLIENT_SECRET: SecretStr
    NINJA_SCOPE: str = "monitoring"

    # ── Postgres ─────────────────────────────────────────────────────
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: str = "ninja"

    # ── Ingest behavior ──────────────────────────────────────────────
    INGEST_SCHEDULE_HOURS: int = Field(default=1, ge=1, le=24)
    PATCH_INGEST_SCHEDULE_HOURS: int | None = Field(default=None, ge=1, le=24)
    # Documentation sources (Hudu) collect independently from agent telemetry.
    # The scheduler caps the effective interval at four hours so inventory
    # evidence does not remain stale across normal deployment activity.
    DOCUMENTATION_SCHEDULE_HOURS: int = Field(default=4, ge=1, le=168)
    SOFTWARE_INGEST_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=168)
    # The classifier's dominant input is installed software, which changes
    # daily at most, so it shares the software ingest cadence rather than the
    # faster intel one. Intel enrichment reaches it through the separately
    # scheduled matcher/Winget/Chocolatey jobs.
    SOFTWARE_CLASSIFY_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=168)
    # The routine software findings run covers only titles in the change feed,
    # so a fleet-wide run is the safety net. Daily keeps every finding's
    # condition assessment inside the 48-hour policy freshness window.
    SOFTWARE_CLASSIFY_FULL_REBUILD_HOURS: int = Field(default=24, ge=24, le=720)
    PATCH_CLASSIFY_FULL_REBUILD_HOURS: int = Field(default=168, ge=24, le=720)
    SOFTWARE_QUEUE_ENABLED: bool = False
    # When disabled, the durable schedule producer does not admit scheduled
    # work. Operator-requested Jobs remain available through the normal queue.
    SCHEDULED_JOBS_ENABLED: bool = True
    SOFTWARE_QUEUE_POLL_MINUTES: int = Field(default=5, ge=1, le=60)
    SOFTWARE_QUEUE_WORKER_BATCH: int = Field(default=3, ge=1, le=20)
    INGEST_LOG_LEVEL: str = "INFO"
    INGEST_HTTP_PORT: int = 8090

    # ── Activities filter (see .env.example for rationale) ───────────
    INGEST_ACTIVITY_SOURCES: str = "PATCH_MANAGEMENT"
    INGEST_ACTIVITY_TYPES_INCLUDE: str = ""

    # ── Custom fields filter ─────────────────────────────────────────
    # Empty = ingest every field (chatty). Set a comma-separated
    # allowlist to keep only the fields you actually use in dashboards.
    INGEST_CUSTOM_FIELDS_INCLUDE: str = ""
    # Cap on value_text length per cell (rebootReason etc. can be 20k+).
    INGEST_CUSTOM_FIELDS_MAX_TEXT: int = 4000
    # Optional allowlist of policy names that should be treated as
    # patching-enabled for servers. Empty = no policy-based server include.
    INGEST_PATCHING_ENABLED_POLICIES: str = ""

    # ── Dashboard view filters ───────────────────────────────────────
    # Comma-separated patch category types (Ninja's `type` value) to
    # hide from every patch-context dashboard query. Empty = show all.
    # Default excludes DRIVER_UPDATES since the operator is not
    # currently installing drivers.
    DASHBOARD_PATCH_CATEGORIES_EXCLUDE: str = "DRIVER_UPDATES"

    # ── Notifications ────────────────────────────────────────────────
    NOTIFY_ENABLED: bool = False
    NOTIFY_DISPATCH_SCHEDULE_MINUTES: int = Field(default=60, ge=5, le=1440)
    NOTIFY_DIGEST_ENABLED: bool = False
    NOTIFY_DIGEST_HOUR: int = Field(default=8, ge=0, le=23)
    NOTIFY_SMTP_HOST: str = ""
    NOTIFY_SMTP_PORT: int = 587
    NOTIFY_SMTP_USERNAME: str = ""
    NOTIFY_SMTP_PASSWORD: SecretStr = SecretStr("")
    NOTIFY_SMTP_STARTTLS: bool = True
    NOTIFY_EMAIL_FROM: str = ""
    NOTIFY_EMAIL_TO: str = ""
    NOTIFY_ZENDESK_URL: str = ""
    NOTIFY_ZENDESK_REQUESTER_EMAIL: str = ""
    NOTIFY_ZENDESK_REQUESTER_NAME: str = "Operations"
    NOTIFY_ZENDESK_AUTH_USERNAME: str = ""
    NOTIFY_ZENDESK_AUTH_TOKEN: SecretStr = SecretStr("")

    @property
    def activity_sources(self) -> list[str]:
        return [s.strip() for s in self.INGEST_ACTIVITY_SOURCES.split(",") if s.strip()]

    @property
    def activity_types_include(self) -> set[str]:
        """Empty set = accept everything from the configured sources."""
        return {s.strip() for s in self.INGEST_ACTIVITY_TYPES_INCLUDE.split(",") if s.strip()}

    @property
    def custom_fields_include(self) -> set[str]:
        """Empty set = include every field name."""
        return {s.strip() for s in self.INGEST_CUSTOM_FIELDS_INCLUDE.split(",") if s.strip()}

    @property
    def patching_enabled_policies(self) -> set[str]:
        """Empty set = no policy-based enablement for server patching."""
        return {
            s.strip()
            for s in self.INGEST_PATCHING_ENABLED_POLICIES.split(",")
            if s.strip()
        }

    @property
    def dashboard_patch_categories_exclude(self) -> tuple[str, ...]:
        """Empty tuple = no exclusion. Order preserved for SQL rendering."""
        return tuple(
            s.strip()
            for s in self.DASHBOARD_PATCH_CATEGORIES_EXCLUDE.split(",")
            if s.strip()
        )

    # ── Intel connectors (ADR 0008) ──────────────────────────────────
    INTEL_ENABLED: bool = False
    INTEL_NVD_ENABLED: bool = True
    INTEL_CISA_KEV_ENABLED: bool = True
    INTEL_EPSS_ENABLED: bool = True
    INTEL_WINGET_ENABLED: bool = True
    INTEL_CHOCOLATEY_ENABLED: bool = True
    INTEL_OTX_ENABLED: bool = True
    INTEL_ABUSECH_ENABLED: bool = True
    INTEL_ENDOFLIFE_ENABLED: bool = True
    NVD_API_KEY: SecretStr = SecretStr("")
    OTX_API_KEY: SecretStr = SecretStr("")
    ABUSECH_AUTH_KEY: SecretStr = SecretStr("")
    VT_API_KEY: SecretStr = SecretStr("")
    MD_API_KEY: SecretStr = SecretStr("")
    CIRCL_AUTH: SecretStr = SecretStr("")
    INTEL_NVD_SCHEDULE_HOURS: int = Field(default=6, ge=1, le=48)
    INTEL_KEV_SCHEDULE_HOURS: int = Field(default=1, ge=1, le=24)
    INTEL_EPSS_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=48)
    INTEL_CATALOG_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=168)
    INTEL_OSINT_SCHEDULE_HOURS: int = Field(default=6, ge=1, le=24)
    INTEL_MATCHER_SCHEDULE_HOURS: int = Field(default=6, ge=1, le=24)
    # Capability recognition (endpoint_security / rmm / remote_access).
    # Phase 1 is shadow mode: assertions are recorded and nothing enforces
    # them. Shares the catalog cadence -- rules change on the order of
    # weeks, and the projector reads only local tables.
    INTEL_CAPABILITY_ENABLED: bool = True
    INTEL_CAPABILITY_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=168)
    # General category recognition (browser / dev_tools / media / ...), a
    # different axis from capability -- see migration 104. Shares the catalog
    # cadence for the same reason capability does: it reads only local tables
    # (safety_signal tag rows the Winget/Chocolatey enrichers already wrote on
    # that cadence), so running it more often would not find new evidence.
    INTEL_CATEGORY_ENABLED: bool = True
    INTEL_CATEGORY_SCHEDULE_HOURS: int = Field(default=24, ge=1, le=168)
    INTEL_LOLRMM_ENABLED: bool = True
    # Phase 4 is code-complete but intentionally fails closed until every
    # sanctioned platform has production product-identity mappings. A product
    # name substring is not an acceptable temporary exemption.
    CAPABILITY_ENFORCEMENT_ENABLED: bool = False
    CAPABILITY_REVIEW_FINDINGS_ENABLED: bool = False

    @property
    def patch_ingest_schedule_hours(self) -> int:
        return self.PATCH_INGEST_SCHEDULE_HOURS or self.INGEST_SCHEDULE_HOURS

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD.get_secret_value()}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()  # type: ignore[call-arg]
