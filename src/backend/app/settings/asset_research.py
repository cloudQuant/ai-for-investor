"""Multi-asset research scheduler, task worker and report-LLM settings.

Multi-asset research: the shadow-schedule worker, the interactive task
runner, the outcome evaluator, source concurrency and the optional report
LLM token/cost budgets.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field


class AssetResearchSettingsMixin:
    """Multi-asset research scheduler, task worker and report-LLM settings."""

    ASSET_RESEARCH_SCHEDULE_ENABLED: bool = Field(
        default=False,
        description="Enable the database-backed multi-asset shadow-schedule worker",
    )

    ASSET_RESEARCH_TASK_RUNNER_ENABLED: bool = Field(
        default=True,
        description="Enable the database-backed interactive multi-asset task worker",
    )

    ASSET_RESEARCH_TASK_POLL_SECONDS: int = Field(
        default=10,
        ge=1,
        le=3600,
        description="Polling cadence for queued interactive multi-asset research tasks",
    )

    ASSET_RESEARCH_TASK_LEASE_SECONDS: int = Field(
        default=900,
        ge=60,
        le=7200,
        description="Durable lease duration for one interactive multi-asset task",
    )

    ASSET_RESEARCH_TASK_MAX_BATCH: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum queued interactive research tasks claimed in one worker cycle",
    )

    ASSET_RESEARCH_TASK_WORKER_CONCURRENCY: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum in-process interactive research task executions per cycle",
    )

    ASSET_RESEARCH_OPERATOR_JURISDICTION: str = Field(
        default="CN",
        min_length=2,
        max_length=32,
        description="Server-owned operating jurisdiction for asset-research publication policy",
    )

    ASSET_RESEARCH_DIRECTIONAL_FX_CRYPTO_ENABLED: bool = Field(
        default=False,
        description="Allow public FX/crypto directions outside mainland China after approvals",
    )

    ASSET_RESEARCH_SCHEDULE_POLL_SECONDS: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Polling cadence for due multi-asset shadow schedules",
    )

    ASSET_RESEARCH_SCHEDULE_LEASE_SECONDS: int = Field(
        default=900,
        ge=60,
        le=7200,
        description="Durable lease duration for one multi-asset schedule fire",
    )

    ASSET_RESEARCH_SCHEDULE_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum immutable retries for one failed schedule fire",
    )

    ASSET_RESEARCH_SCHEDULE_MISFIRE_GRACE_SECONDS: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="Lateness tolerated before a schedule misfire policy is applied",
    )

    ASSET_RESEARCH_SCHEDULE_RETRY_BASE_SECONDS: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Initial exponential-backoff delay for asset schedule retries",
    )

    ASSET_RESEARCH_SCHEDULE_RETRY_MAX_SECONDS: int = Field(
        default=3600,
        ge=10,
        le=86400,
        description="Maximum exponential-backoff delay for asset schedule retries",
    )

    ASSET_RESEARCH_SCHEDULE_MAX_BATCH: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Maximum due multi-asset schedules claimed in one approved capacity cycle",
    )

    ASSET_RESEARCH_SCHEDULE_WORKER_CONCURRENCY: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum in-process multi-asset schedule executions per poll",
    )

    ASSET_RESEARCH_SOURCE_MAX_CONCURRENCY: int = Field(
        default=2,
        ge=1,
        le=16,
        description="Maximum in-process collection attempts per declared asset-data source",
    )

    ASSET_RESEARCH_AKSHARE_PROVIDER_ENABLED: bool = Field(
        default=False,
        description="Enable approved AkShare-backed futures/bond providers for asset research",
    )

    ASSET_RESEARCH_OUTCOME_EVALUATOR_ENABLED: bool = Field(
        default=False,
        description="Enable the database-backed multi-asset outcome evaluator worker",
    )

    ASSET_RESEARCH_OUTCOME_EVALUATOR_POLL_SECONDS: int = Field(
        default=300,
        ge=30,
        le=86400,
        description="Polling cadence for mature multi-asset outcome evaluation",
    )

    ASSET_RESEARCH_OUTCOME_EVALUATOR_LEASE_SECONDS: int = Field(
        default=900,
        ge=60,
        le=7200,
        description="Durable lease duration for one multi-asset outcome evaluation",
    )

    ASSET_RESEARCH_OUTCOME_EVALUATOR_MAX_BATCH: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum mature predictions claimed in one outcome evaluator poll",
    )

    ASSET_RESEARCH_LLM_REPORT_ENABLED: bool = Field(
        default=False,
        description="Enable optional LLM-generated multi-asset report sections",
    )

    ASSET_RESEARCH_LLM_MODEL: str = Field(
        default="",
        description="Model name for optional asset-research report generation",
    )

    ASSET_RESEARCH_LLM_PROVIDER: str = Field(
        default="",
        description="Provider key from the AI provider registry for asset-research LLM",
    )

    ASSET_RESEARCH_LLM_BASE_URL: str | None = Field(
        default=None,
        description="Optional OpenAI-compatible base URL for asset-research LLM",
    )

    ASSET_RESEARCH_LLM_API_KEY_ENV: str | None = Field(
        default=None,
        description="Environment variable name containing the asset-research LLM API key",
    )

    ASSET_RESEARCH_LLM_MAX_TOKENS: int = Field(
        default=6000,
        ge=256,
        le=32768,
        description="Maximum output tokens requested for one asset-research report",
    )

    ASSET_RESEARCH_LLM_PER_TASK_TOKENS: int = Field(
        default=30000,
        ge=1000,
        le=200000,
        description="Per-task LLM token budget for asset-research reports",
    )

    ASSET_RESEARCH_LLM_DAILY_TOKENS: int = Field(
        default=100000,
        ge=1000,
        le=5000000,
        description="Daily LLM token budget for asset-research reports",
    )

    ASSET_RESEARCH_LLM_MONTHLY_TOKENS: int = Field(
        default=1000000,
        ge=1000,
        le=50000000,
        description="Monthly LLM token budget for asset-research reports",
    )

    ASSET_RESEARCH_LLM_PER_TASK_COST_USD: float = Field(
        default=0.1,
        ge=0,
        le=100,
        description="Per-task LLM cost budget in USD for asset-research reports",
    )

    ASSET_RESEARCH_LLM_DAILY_COST_USD: float = Field(
        default=1.0,
        ge=0,
        le=10000,
        description="Daily LLM cost budget in USD for asset-research reports",
    )

    ASSET_RESEARCH_LLM_MONTHLY_COST_USD: float = Field(
        default=10.0,
        ge=0,
        le=100000,
        description="Monthly LLM cost budget in USD for asset-research reports",
    )
