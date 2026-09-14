"""Configuration.

Every tunable in the system lives here, loaded from the environment with a
documented default. Scoring code reads these values; it never carries its own
constants.
"""

from __future__ import annotations

import functools

from pydantic import Field, PostgresDsn, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECTORS = (
    "Technology,Telecommunications,Oil & Gas,Energy,Banking,Fintech,FMCG,"
    "Automotive,Pharma,Healthcare,Real Estate,Construction,Engineering,"
    "Industrial,Manufacturing"
)


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Runtime configuration, assembled from the environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- application -----------------------------------------------------
    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- database --------------------------------------------------------
    postgres_db: str = "paradigm"
    postgres_user: str = "paradigm"
    postgres_password: str = "paradigm"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- AI --------------------------------------------------------------
    ai_provider: str = "rule_based"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    ai_max_output_tokens: int = 2000
    ai_timeout_seconds: float = 60.0

    # --- market scope ----------------------------------------------------
    target_country: str = "EG"
    sectors: list[str] = Field(default_factory=lambda: _split_csv(DEFAULT_SECTORS))

    # --- Top 50 ----------------------------------------------------------
    top_n: int = 50
    min_qualifying_score: int = 70

    # --- scoring weights (must sum to 1.0) -------------------------------
    weight_event_probability: float = 0.35
    weight_commercial_value: float = 0.25
    weight_contact_quality: float = 0.20
    weight_timing: float = 0.10
    weight_evidence: float = 0.10

    # --- conservatism ----------------------------------------------------
    event_probability_exponent: float = 1.25
    event_probability_cap_unconfirmed: int = 95
    #: ``probability <= evidence_cap_base + evidence_cap_slope * evidence_score``
    evidence_cap_base: float = 55.0
    evidence_cap_slope: float = 0.45

    # --- contact damping -------------------------------------------------
    contact_quality_floor: int = 40
    contact_quality_weak_multiplier: float = 0.5
    contact_corroboration_bonus: int = 3
    contact_corroboration_max_bonus: int = 9

    # --- decay -----------------------------------------------------------
    decay_grace_days: int = 14
    decay_tau_days: float = 120.0
    decay_floor: float = 0.20
    missed_window_penalty: float = 0.60
    thin_evidence_threshold: int = 40
    thin_evidence_penalty: float = 0.90

    # --- ingestion -------------------------------------------------------
    sources_config: str = "config/sources.json"
    ingest_lookback_days: int = 30
    ingest_max_docs_per_source: int = 50
    ingest_user_agent: str = (
        "ParadigmIntelligence/1.0 (+sales-intelligence; contact via repository owner)"
    )
    ingest_http_timeout: float = 30.0
    #: Default politeness budget per host. A source may lower it, never raise it
    #: past what its own config asks for.
    ingest_default_rate_limit_per_minute: float = 20.0
    ingest_max_attempts: int = 3
    ingest_max_backoff_seconds: float = 30.0
    #: Hard ceiling on a single response, so one enormous page cannot exhaust
    #: memory during a run.
    ingest_max_response_bytes: int = 5_000_000

    # --- relevance filter (spec §10) -------------------------------------
    relevance_enabled: bool = True
    relevance_min_chars: int = 120
    relevance_min_score: int = 20
    #: Business hits needed to keep a document that names no corporate actor.
    relevance_min_business_hits: int = 3
    #: Noise terms needed before noise is even considered decisive.
    relevance_noise_hits: int = 3
    #: Business hits that override a noise marker. A story can mention football
    #: sponsorship and still be a real sponsorship opportunity.
    relevance_noise_override_hits: int = 4

    # --- brief -----------------------------------------------------------
    brief_lookback_hours: int = 24
    #: Spec §25 asks for the top 10 new opportunities.
    brief_top_new_limit: int = 10
    brief_top_changed_limit: int = 10

    # --- API -------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    api_prefix: str = "/api/v1"
    #: Shared secret for /api/v1. Empty means open access, which is refused
    #: outside development (see app/api/security.py).
    api_key: str | None = None

    # --- scheduler (spec §46) --------------------------------------------
    scheduler_enabled: bool = False
    #: Hours between automatic ingestion cycles.
    scheduler_interval_hours: float = 6.0
    #: Delay before the first cycle, so start-up is not competing with it.
    scheduler_initial_delay_seconds: float = 60.0

    @field_validator("sectors", "cors_origins", mode="before")
    @classmethod
    def _parse_csv_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return _split_csv(value)
        return value

    @field_validator("ai_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        allowed = {"anthropic", "rule_based"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"AI_PROVIDER must be one of {sorted(allowed)}, got {value!r}")
        return normalized

    @model_validator(mode="after")
    def _validate_weights(self) -> Settings:
        """Fail fast on a mis-weighted configuration.

        A weight vector that does not sum to 1.0 silently skews every score in
        the system, so it is a startup error rather than a runtime surprise.
        """
        total = (
            self.weight_event_probability
            + self.weight_commercial_value
            + self.weight_contact_quality
            + self.weight_timing
            + self.weight_evidence
        )
        if abs(total - 1.0) > 1e-3:
            raise ValueError(
                "Scoring weights must sum to 1.0 "
                f"(got {total:.4f}). Check the WEIGHT_* environment variables."
            )
        if not 0 <= self.min_qualifying_score <= 100:
            raise ValueError("MIN_QUALIFYING_SCORE must be between 0 and 100")
        if self.top_n < 1:
            raise ValueError("TOP_N must be at least 1")
        if not 0.0 < self.decay_floor <= 1.0:
            raise ValueError("DECAY_FLOOR must be in (0, 1]")
        if self.decay_tau_days <= 0:
            raise ValueError("DECAY_TAU_DAYS must be positive")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        """The URL SQLAlchemy connects with.

        ``DATABASE_URL`` wins when set, so a managed-database connection string
        can be dropped in without decomposing it into parts.
        """
        if self.database_url:
            return self.database_url
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    def is_known_sector(self, sector: str | None) -> bool:
        """True when ``sector`` is one of the configured priority sectors."""
        if not sector:
            return False
        return sector.strip().casefold() in {s.casefold() for s in self.sectors}

    def canonical_sector(self, sector: str | None) -> str | None:
        """Map a loosely-cased sector onto its configured spelling.

        Returns ``None`` for anything unrecognised rather than inventing a
        sector — an unknown sector is data we do not have.
        """
        if not sector:
            return None
        wanted = sector.strip().casefold()
        for configured in self.sectors:
            if configured.casefold() == wanted:
                return configured
        return None


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
