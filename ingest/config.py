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
load_dotenv(Path("/app/.env"), override=False)


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
    AGENT_COMPLIANCE_ENABLED: bool = False
    AGENT_COMPLIANCE_SCHEDULE_HOURS: int = Field(default=4, ge=1, le=24)
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

    # ── Metabase auto-bootstrap (optional) ───────────────────────────
    # If MB_BOOTSTRAP_USER and MB_BOOTSTRAP_PASS are both set, ingest
    # runs the dashboard bootstrap script on startup in a background
    # thread. Failures are logged but don't crash ingest. Empty values
    # disable the auto-run (script can still be triggered manually via
    # `docker exec ninja-ingest python -m ingest.metabase_bootstrap`).
    MB_BOOTSTRAP_URL: str = "http://metabase:3000"
    MB_BOOTSTRAP_USER: str = ""
    MB_BOOTSTRAP_PASS: SecretStr = SecretStr("")
    MB_BOOTSTRAP_DB_NAME: str = "Ninja"

    # ── Agent compliance alerts ──────────────────────────────────────
    AGENT_COMPLIANCE_ALERTS_ENABLED: bool = False
    AGENT_COMPLIANCE_ALERT_COOLDOWN_HOURS: int = Field(default=24, ge=1, le=168)
    AGENT_COMPLIANCE_ALERT_WEBHOOK_URL_REF: str = "AGENT_COMPLIANCE_ALERT_WEBHOOK_URL"
    AGENT_COMPLIANCE_ALERT_EMAIL_FROM: str = ""
    AGENT_COMPLIANCE_ALERT_EMAIL_TO: str = ""
    AGENT_COMPLIANCE_SMTP_HOST: str = ""
    AGENT_COMPLIANCE_SMTP_PORT: int = 587
    AGENT_COMPLIANCE_SMTP_USERNAME: str = ""
    AGENT_COMPLIANCE_SMTP_PASSWORD: SecretStr = SecretStr("")
    AGENT_COMPLIANCE_SMTP_STARTTLS: bool = True
    AGENT_COMPLIANCE_ZENDESK_URL: str = ""
    AGENT_COMPLIANCE_ZENDESK_REQUESTER_EMAIL: str = ""
    AGENT_COMPLIANCE_ZENDESK_REQUESTER_NAME: str = "Agent Compliance"
    AGENT_COMPLIANCE_ZENDESK_AUTH_USERNAME: str = ""
    AGENT_COMPLIANCE_ZENDESK_AUTH_TOKEN: SecretStr = SecretStr("")

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
