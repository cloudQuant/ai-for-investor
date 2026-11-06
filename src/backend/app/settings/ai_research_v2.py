"""Trusted AI-research protocol-v2 worker settings.

Trusted AI-research protocol v2: the separately deployed Explorer,
generation and sealed-holdout workers, their pinned endpoints, sandbox
limits and quota leases. Defaults are deliberately incomplete so that a
rollout flag alone cannot create a usable remote-execution path.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from typing import Literal

from pydantic import Field, SecretStr


class AiResearchV2SettingsMixin:
    """Trusted AI-research protocol-v2 worker settings."""

    AI_RESEARCH_PROTOCOL_V2_ENABLED: bool = Field(
        default=False,
        description="Enable new trusted AI-research v2 write operations for an approved scope",
    )

    AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION: Literal["generation-v1", "discovery-v1"] = Field(
        default="generation-v1",
        description=(
            "Server-owned protocol-v2 workflow selected for newly submitted research runs; "
            "clients cannot override it"
        ),
    )

    AI_RESEARCH_PROTOCOL_V2_WORKER_ENABLED: bool = Field(
        default=False,
        description="Enable the separately deployed trusted-research Explorer worker",
    )

    AI_RESEARCH_PROTOCOL_V2_WORKER_FACTORY: str = Field(
        default="",
        max_length=512,
        description=(
            "Reviewed app.research_deployments factory reference used only by the Explorer worker"
        ),
    )

    AI_RESEARCH_PROTOCOL_V2_WORKER_POLL_SECONDS: float = Field(
        default=10.0,
        ge=0.1,
        le=3600,
        description="Polling cadence for the separately deployed trusted-research Explorer worker",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_WORKER_ENABLED: bool = Field(
        default=False,
        description="Enable the separately deployed sealed-holdout evaluator worker",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_WORKER_FACTORY: str = Field(
        default="",
        max_length=512,
        description="Reviewed app.research_deployments factory for the holdout worker process",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_WORKER_POLL_SECONDS: float = Field(
        default=10.0,
        ge=0.1,
        le=3600,
        description="Polling cadence for the separately deployed sealed-holdout worker",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_ENDPOINT_URL: str = Field(
        default="",
        max_length=2048,
        description="Pinned HTTPS /v1/holdout-executions evaluator endpoint",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_BEARER_TOKEN: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        repr=False,
        description="Deployment-only credential for the sealed evaluator endpoint",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_WORKER_IDENTITY: str = Field(
        default="",
        max_length=512,
        description="Service identity recorded for holdout claim and recovery operations",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_EVALUATOR_IDENTITY: str = Field(
        default="",
        max_length=512,
        description="Pinned independent evaluator identity expected in holdout receipts",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_EVALUATOR_IMAGE_DIGEST: str = Field(
        default="",
        max_length=128,
        description="Pinned sha256 evaluator image digest expected in holdout receipts",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_HTTP_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        gt=0,
        le=3600,
        description="Whole HTTP deadline for sealed holdout execute and inspect calls",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_MAX_RESPONSE_BYTES: int = Field(
        default=10_000_000,
        ge=1,
        le=10_000_000,
        description="Maximum accepted sealed evaluator response bytes",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_LEASE_SECONDS: int = Field(
        default=300,
        ge=1,
        le=7200,
        description="Database lease duration for one holdout command claim",
    )

    AI_RESEARCH_PROTOCOL_V2_HOLDOUT_HEARTBEAT_SECONDS: float = Field(
        default=30.0,
        gt=0,
        le=2400,
        description="Heartbeat cadence while a sealed evaluator request is active",
    )

    AI_RESEARCH_PROTOCOL_V2_DATASET_OBJECT_RESOLVER_TYPE: str = Field(
        default="",
        max_length=32,
        description="Exact deployment-owned protocol-v2 dataset resolver type; empty disables it",
    )

    AI_RESEARCH_PROTOCOL_V2_DATASET_FILESYSTEM_ROOT: str = Field(
        default="",
        max_length=2048,
        description="Absolute controlled object root for the reviewed filesystem dataset resolver",
    )

    AI_RESEARCH_PROTOCOL_V2_DATASET_RECEIPT_STORE: str = Field(
        default="",
        max_length=2048,
        description="Separate absolute receipt store for the reviewed filesystem dataset resolver",
    )

    AI_RESEARCH_PROTOCOL_V2_DATASET_MAX_BYTES: int = Field(
        default=0,
        ge=0,
        le=10 * 1024 * 1024 * 1024,
        description="Maximum byte size for a filesystem dataset object; zero keeps resolver disabled",
    )

    # The real GENERATE deployment remains opt-in behind the two protocol/worker
    # flags above.  These static settings are intentionally separate from the
    # user-facing AI provider registry: a worker image chooses one reviewed
    # route, prompt, quota policy, and materialization manifest at startup.
    AI_RESEARCH_PROTOCOL_V2_GENERATION_PROVIDER_ID: str = Field(
        default="",
        max_length=256,
        description="Reviewed provider route identity for the opt-in v2 generation worker",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_ENDPOINT_URL: str = Field(
        default="",
        max_length=2048,
        description="Pinned HTTPS chat-completions endpoint for the v2 generation worker",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MODEL_ALIAS: str = Field(
        default="",
        max_length=256,
        description="Server-owned model alias requested by the v2 generation executor",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MODEL_ID: str = Field(
        default="",
        max_length=256,
        description="Pinned provider model identity resolved from the generation alias",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_API_KEY: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        repr=False,
        description="Deployment-only credential for the pinned v2 generation provider route",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        gt=0,
        le=600,
        description="Total provider request timeout for the v2 generation worker",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MAX_OUTPUT_TOKENS: int = Field(
        default=1024,
        ge=1,
        le=131_072,
        description="Fixed maximum generated tokens; deployment verifies it fits the quota reserve",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MAX_RESPONSE_BYTES: int = Field(
        default=2 * 1024 * 1024,
        ge=1,
        le=16 * 1024 * 1024,
        description="Maximum accepted provider response bytes for v2 generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MAX_REQUEST_BYTES: int = Field(
        default=512 * 1024,
        ge=1,
        le=1024 * 1024,
        description="Maximum serialized provider request bytes for v2 generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_PROMPT_TEMPLATE_VERSION: str = Field(
        default="",
        max_length=128,
        description="Immutable deployment prompt-template version for v2 generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_PROMPT_CONTENT: str = Field(
        default="",
        max_length=256 * 1024,
        description="Fixed deployment prompt content for v2 generation; never selected by a browser",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_PROMPT_CONTENT_HASH: str = Field(
        default="",
        max_length=128,
        description="Canonical hash of the fixed deployment generation prompt",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_SAMPLING_PARAMS_JSON: str = Field(
        default="{}",
        max_length=64 * 1024,
        description="Static JSON object of approved sampling parameters for v2 generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_QUOTA_POLICY_VERSION: str = Field(
        default="",
        max_length=128,
        description="Server-owned quota policy version for v2 generation reservations",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_ACCOUNTING_POLICY_JSON: str = Field(
        default="",
        max_length=16 * 1024,
        description="Reviewed all-inclusive provider accounting contract; empty denies real generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_ACCOUNTING_POLICY_HASH: str = Field(
        default="",
        max_length=64,
        description="Deployment-reviewed canonical hash of the accounting contract, not provider proof",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_RESERVED_TOKENS: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        description="Total input-plus-output token ceiling per v2 call; zero denies deployment",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_QUOTA_LEASE_SECONDS: int = Field(
        default=900,
        ge=1,
        le=24 * 60 * 60,
        description="Lease duration for the fixed v2 generation quota reservation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_MATERIALIZATION_POLICY_VERSION: str = Field(
        default="",
        max_length=128,
        description="Immutable deployment materialization-policy version for v2 generation",
    )

    AI_RESEARCH_PROTOCOL_V2_GENERATION_ENVIRONMENT_MANIFEST_JSON: str = Field(
        default="{}",
        max_length=64 * 1024,
        description="Static nonempty JSON environment manifest for v2 candidate materialization",
    )

    # Discovery executes only through a separately deployed, pinned HTTPS
    # runner. Defaults are deliberately incomplete so enabling either rollout
    # flag alone cannot create a usable remote-execution path.
    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_ENDPOINT_URL: str = Field(
        default="",
        max_length=2048,
        description="Pinned HTTPS /v1/discovery-executions endpoint for the v2 discovery runner",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_BEARER_TOKEN: SecretStr = Field(
        default_factory=lambda: SecretStr(""),
        repr=False,
        description="Deployment-only credential for the pinned v2 discovery runner",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_RUNNER_IDENTITY: str = Field(
        default="",
        max_length=512,
        description="Pinned service identity expected in discovery-runner evidence",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_HTTP_TIMEOUT_SECONDS: float = Field(
        default=0.0,
        ge=0,
        le=3660,
        description="Whole HTTP deadline for discovery execution; deployment validates policy margin",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_POLICY_VERSION: str = Field(
        default="",
        max_length=128,
        description="Immutable server-owned sandbox policy version for discovery",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_IMAGE_DIGEST: str = Field(
        default="",
        max_length=128,
        description="Pinned sha256 image digest accepted from the discovery runner",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_NETWORK_MODE: str = Field(
        default="",
        max_length=32,
        description="Pinned sandbox network mode; discovery policy requires none",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_INPUT_READ_ONLY: bool = Field(
        default=False,
        description="Require read-only discovery sandbox inputs",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_OUTPUT_PATH: str = Field(
        default="",
        max_length=2048,
        description="Pinned sandbox-owned output path for discovery evidence",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_CPU_LIMIT: int = Field(
        default=0,
        ge=0,
        le=1024,
        description="Discovery sandbox CPU limit; zero leaves deployment fail-closed",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_MEMORY_LIMIT_MB: int = Field(
        default=0,
        ge=0,
        le=16 * 1024 * 1024,
        description="Discovery sandbox memory limit in MiB; zero leaves deployment fail-closed",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_PID_LIMIT: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
        description="Discovery sandbox process limit; zero leaves deployment fail-closed",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_WALL_TIMEOUT_SECONDS: int = Field(
        default=0,
        ge=0,
        le=3600,
        description="Discovery sandbox wall-clock timeout; zero leaves deployment fail-closed",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_SANDBOX_OUTPUT_LIMIT_BYTES: int = Field(
        default=0,
        ge=0,
        le=100 * 1024 * 1024,
        description="Maximum retained discovery sandbox output bytes; zero leaves deployment fail-closed",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_QUOTA_POLICY_VERSION: str = Field(
        default="",
        max_length=128,
        description="Server-owned discovery sandbox-seconds quota policy version",
    )

    AI_RESEARCH_PROTOCOL_V2_DISCOVERY_QUOTA_LEASE_SECONDS: int = Field(
        default=0,
        ge=0,
        le=24 * 60 * 60,
        description="Discovery quota lease; deployment validates the required wall-time margin",
    )

    AI_RESEARCH_PROTOCOL_V2_GOVERNANCE_POLICY_VERSION: str = Field(
        default="governance-v1",
        min_length=1,
        max_length=128,
        description="Server-owned version for trusted-research governance deviations",
    )

    AI_RESEARCH_PROTOCOL_V2_WAIVABLE_TARGETS: str = Field(
        default="",
        description="Comma-separated server allowlist of waivable trusted-research performance targets",
    )
