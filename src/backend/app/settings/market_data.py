"""Market-data provider, akshare collection and stock-signal settings.

The market-data plane: the Iteration 197 normalized query API, the OpenBB,
THS and OpenData provider routes, the akshare collection scheduler and the
after-close stock-signal worker.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

import re

from pydantic import Field, field_validator

from app.services.market_data.openbb_runtime import SUPPORTED_OPENBB_RUNNER_PROVIDERS
from app.settings.paths import REPO_ROOT as _REPO_ROOT

_MARKET_DATA_PROVIDER_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class MarketDataSettingsMixin:
    """Market-data provider, akshare collection and stock-signal settings."""

    MARKET_DATA_QUERY_V2_ENABLED: bool = Field(
        default=False,
        description="Expose the Iteration 197 normalized market-data query API",
    )

    MARKET_DATA_ONLINE_FETCH_ENABLED: bool = Field(
        default=False,
        description="Allow the normalized market-data query API to invoke approved providers",
    )

    MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED: bool = Field(
        default=False,
        description=(
            "Allow an explicitly requested strategy-data cache fill with research source authorization"
        ),
    )

    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED: bool = Field(
        default=False,
        description=(
            "Bind AI strategy research backtests to strict local-only Iteration 197 data artifacts"
        ),
    )

    MARKET_DATA_RESEARCH_ARTIFACT_ROOT: str = Field(
        default=str((_REPO_ROOT / "data" / "market_data_research").resolve()),
        description=("Server-owned root for immutable market-data research/backtest artifacts"),
    )

    MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY: str = Field(
        default="",
        repr=False,
        description=(
            "Operator-managed HMAC key used to verify server-issued research data bindings"
        ),
    )

    MARKET_DATA_CURSOR_SIGNING_KEY: str = Field(
        default="",
        repr=False,
        description=(
            "Operator-managed HMAC key for normalized market-data pagination cursors; "
            "required when the v2 query API is enabled"
        ),
    )

    MARKET_DATA_OPENBB_PROVIDER: str = Field(
        default="yfinance",
        description="Approved OpenBB provider identifier used by the isolated runner",
    )

    MARKET_DATA_OPENBB_ALLOWED_MARKETS: str = Field(
        default="",
        description=(
            "Comma-separated master-data venues that may narrow an explicit OpenBB permit; "
            "they cannot enable a route on their own"
        ),
    )

    MARKET_DATA_THS_ENABLED: bool = Field(
        default=False,
        description=(
            "叠加 kill-switch for the Iteration 198 THS provider routes. THS routing is "
            "fail-closed by default and additionally requires a durable capability ledger "
            "attestation, an active provider registry row, and a source authorization grant; "
            "this flag only removes THS routes from the assembled policy."
        ),
    )

    MARKET_DATA_OPENDATA_ENABLED: bool = Field(
        default=False,
        description=(
            "叠加 kill-switch for the opendata (self-hosted data platform) provider route. "
            "opendata routing is fail-closed by default and additionally requires a durable "
            "capability ledger attestation, an active provider registry row, and a source "
            "authorization grant; this flag only removes the route from the assembled policy."
        ),
    )

    MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED: bool = Field(
        default=False,
        description=(
            "Default-off OpenData selector for HS300, CSI500, and CSI800 in the risk benchmark "
            "and benchmark-metrics APIs only. It also requires MARKET_DATA_OPENDATA_ENABLED, "
            "current read and source-governance authorization, and durable attestation for the "
            "exact index route. Other consumers using the default BenchmarkService fail closed "
            "for these indices until migrated; this flag does not switch them to OpenData. "
            "Missing grants, coverage, credentials, or data never fall back to AkShare."
        ),
    )

    MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED: bool = Field(
        default=False,
        description="Use the reviewed OpenData published stock reference catalog for selector options",
    )

    MARKET_DATA_OPENDATA_INSTRUMENT_DATASET_ID: str = Field(
        default="", description="Exact server-owned published instrument reference dataset ID"
    )

    MARKET_DATA_OPENDATA_INSTRUMENT_SOURCE_ID: str = Field(
        default="", description="Exact approved source ID for the instrument reference catalog"
    )

    MARKET_DATA_OPENDATA_INSTRUMENT_CONTRACT_SHA256: str = Field(
        default="", description="Pinned canonical contract SHA-256 for the reference catalog"
    )

    STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED: bool = Field(
        default=False,
        description=(
            "Read source-native ths_fuyao financial archive evidence for A-share stock analysis. "
            "This is default-off, never falls back to AkShare when selected, and does not make "
            "the evidence eligible for normalized analysis or point-in-time decisions."
        ),
    )

    STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS: str = Field(
        default="",
        description=(
            "Comma-separated exact hosts allowed for remote HTTPS OpenData API requests. "
            "A hostname permits port 443; use host:port to permit another exact port. "
            "Loopback hosts remain available for local development; non-loopback HTTP is rejected."
        ),
    )

    STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable explicit per-request OpenData reads of a pinned Sina FZB publication/capture. "
            "Requires the request selector and never discovers or falls back to another provider."
        ),
    )

    STOCK_ANALYSIS_OPENDATA_SINA_FZB_ALLOWED_HOSTS: str = Field(
        default="",
        description=(
            "Comma-separated exact hosts allowed for explicit Sina FZB OpenData API reads. "
            "Remote endpoints require HTTPS and an exact host allowlist."
        ),
    )

    STOCK_ANALYSIS_OPENDATA_SINA_LRB_SNAPSHOT_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable explicit per-request OpenData reads of a pinned Sina LRB source-native "
            "snapshot. The atemporal node-table evidence is provenance only and never enters "
            "financial metrics, scoring, or AI prompts."
        ),
    )

    STOCK_ANALYSIS_OPENDATA_SINA_LRB_ALLOWED_HOSTS: str = Field(
        default="",
        description=(
            "Comma-separated exact hosts allowed for explicit Sina LRB OpenData API reads. "
            "Remote endpoints require HTTPS and an exact host allowlist."
        ),
    )

    MARKET_DATA_THS_SCHEDULER_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable the Iteration 199 daily THS history collection job (APScheduler). "
            "Requires THS_API_KEY; disabled by default."
        ),
    )

    MARKET_DATA_THS_SCHEDULER_HOUR: int = Field(
        default=18, description="Hour (Asia/Shanghai) for the daily THS collection job"
    )

    MARKET_DATA_THS_SCHEDULER_MINUTE: int = Field(
        default=0, description="Minute for the daily THS collection job"
    )

    MARKET_DATA_THS_SCHEDULER_TIMEZONE: str = Field(
        default="Asia/Shanghai", description="Timezone name for the daily THS collection job"
    )

    AKSHARE_SCHEDULER_TIMEZONE: str = Field(
        default="Asia/Shanghai", description="Scheduler timezone for akshare tasks"
    )

    AKSHARE_SCHEDULER_MAX_CONCURRENT_TASKS: int = Field(
        default=1,
        ge=1,
        description="Maximum concurrent akshare scheduler-triggered tasks",
    )

    AKSHARE_SCRIPT_ROOT: str = Field(
        default="app/data_fetch/scripts", description="Root directory for akshare scripts"
    )

    AKSHARE_INTERFACE_BOOTSTRAP_MODE: str = Field(
        default="manual", description="Akshare interface bootstrap mode: manual or refresh"
    )

    STOCK_SIGNAL_SCHEDULE_ENABLED: bool = Field(
        default=False,
        description="Enable the after-close auditable SSE50 signal scheduler",
    )

    STOCK_SIGNAL_BENCHMARK_OPENDATA_ENABLED: bool = Field(
        default=False,
        description=(
            "Read SSE50 from OpenData; keep disabled until 000016 coverage, daily source "
            "comparison, and monitoring are verified"
        ),
    )

    STOCK_SIGNAL_SCHEDULE_TIMEZONE: str = Field(
        default="Asia/Shanghai", description="Timezone for the stock signal scheduler"
    )

    STOCK_SIGNAL_SCHEDULE_CRON: str = Field(
        default="10 19 * * 1-5", description="Five-field cron expression for stock signals"
    )

    STOCK_SIGNAL_UNIVERSE: str = Field(
        default="sse50", description="Versioned universe identifier for nightly stock signals"
    )

    STOCK_SIGNAL_MAX_CONCURRENCY: int = Field(
        default=4, ge=1, le=10, description="Maximum simultaneous symbol collections"
    )

    STOCK_SIGNAL_MIN_HISTORY_BARS: int = Field(
        default=60, ge=20, le=500, description="Minimum daily bars required for an eligible signal"
    )

    STOCK_SIGNAL_MAX_FINANCIAL_AGE_DAYS: int = Field(
        default=210, ge=30, le=730, description="Maximum financial report age before degradation"
    )

    STOCK_SIGNAL_MAX_NEWS_AGE_DAYS: int = Field(
        default=7, ge=1, le=90, description="Maximum news age before degradation"
    )

    STOCK_SIGNAL_ROUND_TRIP_COST_BPS: float | None = Field(
        default=None,
        ge=0,
        le=1000,
        description="Approved round-trip cost for scheduled evaluations",
    )

    STOCK_SIGNAL_BUY_SUCCESS_THRESHOLD_BPS: float | None = Field(
        default=None,
        ge=0,
        le=5000,
        description="Approved buy-success threshold for scheduled evaluation",
    )

    STOCK_SIGNAL_SELL_SUCCESS_THRESHOLD_BPS: float | None = Field(
        default=None,
        ge=0,
        le=5000,
        description="Approved sell-success threshold for scheduled evaluation",
    )

    @field_validator("AKSHARE_INTERFACE_BOOTSTRAP_MODE")
    @classmethod
    def validate_akshare_interface_bootstrap_mode(cls, v: str) -> str:
        """Validate akshare interface bootstrap mode."""
        normalized = v.strip().lower()
        supported_modes = {"manual", "refresh"}
        if normalized not in supported_modes:
            raise ValueError(
                "AKSHARE_INTERFACE_BOOTSTRAP_MODE must be one of: "
                f"{', '.join(sorted(supported_modes))}"
            )
        return normalized

    @field_validator("MARKET_DATA_OPENBB_PROVIDER")
    @classmethod
    def validate_market_data_openbb_provider(cls, v: str) -> str:
        """Accept only runner providers with a reviewed static contract."""
        normalized = str(v or "").strip().lower()
        if not _MARKET_DATA_PROVIDER_TOKEN_PATTERN.fullmatch(normalized):
            raise ValueError(
                "MARKET_DATA_OPENBB_PROVIDER must be a lowercase provider token up to 128 chars"
            )
        if normalized not in SUPPORTED_OPENBB_RUNNER_PROVIDERS:
            raise ValueError(
                "MARKET_DATA_OPENBB_PROVIDER must be one of: "
                f"{', '.join(sorted(SUPPORTED_OPENBB_RUNNER_PROVIDERS))}"
            )
        return normalized

    @field_validator("MARKET_DATA_OPENBB_ALLOWED_MARKETS")
    @classmethod
    def validate_market_data_openbb_allowed_markets(cls, v: str) -> str:
        """Normalize an operator-reviewed OpenBB venue allow-list without defaults."""
        values = [item.strip() for item in str(v or "").split(",") if item.strip()]
        if any(len(item) > 128 for item in values):
            raise ValueError("MARKET_DATA_OPENBB_ALLOWED_MARKETS values must be at most 128 chars")
        return ",".join(dict.fromkeys(values))

    @field_validator("MARKET_DATA_CURSOR_SIGNING_KEY")
    @classmethod
    def validate_market_data_cursor_signing_key(cls, v: str) -> str:
        """Accept a blank disabled-state value or a high-entropy HMAC secret."""
        normalized = str(v or "").strip()
        if normalized and len(normalized.encode("utf-8")) < 32:
            raise ValueError("MARKET_DATA_CURSOR_SIGNING_KEY must be at least 32 bytes")
        return normalized
