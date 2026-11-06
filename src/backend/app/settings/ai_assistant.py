"""AI chat, local RAG retrieval, provider registry and score-weight settings.

Knowledge-base AI: the chat provider, local RAG retrieval, the AI provider
registry with its budgets, and the strategy-score weights.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from typing import Any

from pydantic import Field, field_validator

from app.ai_provider_registry import get_default_provider_registry
from app.config_parsing import parse_ai_providers, parse_strategy_score_weights


class AiAssistantSettingsMixin:
    """AI chat, local RAG retrieval, provider registry and score-weight settings."""

    AI_CHAT_ENABLED: bool = Field(
        default=False, description="Enable generated AI responses for knowledge-base chat"
    )

    AI_CHAT_BASE_URL: str = Field(
        default="", description="Base URL for an OpenAI-compatible chat completions endpoint"
    )

    AI_CHAT_API_KEY: str = Field(default="", description="API key for AI chat provider")

    AI_CHAT_MODEL: str = Field(default="", description="Model name for AI chat provider")

    AI_CHAT_TIMEOUT: float = Field(
        default=120.0, description="Timeout for AI chat provider requests in seconds"
    )

    AI_CHAT_TEMPERATURE: float = Field(
        default=0.2, description="Sampling temperature for AI chat provider requests"
    )

    AI_CHAT_MAX_TOKENS: int = Field(
        default=4096,
        ge=512,
        le=32768,
        description="Maximum tokens requested from the AI chat provider",
    )

    RAG_VECTOR_ENABLED: bool = Field(
        default=True,
        description="Enable local vector retrieval for knowledge-base chat",
    )

    RAG_EMBEDDING_MODEL: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="Sentence Transformers model used for local RAG embeddings",
    )

    RAG_VECTOR_COLLECTION: str = Field(
        default="knowledge_base_documents_v3",
        description="Local Chroma collection name for knowledge-base document vectors",
    )

    RAG_VECTOR_UPSERT_BATCH_SIZE: int = Field(
        default=128,
        ge=16,
        le=512,
        description="Document vectors processed in one local Chroma upsert batch",
    )

    RAG_LLM_RERANK_TIMEOUT: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Maximum seconds for the short knowledge-base rerank call",
    )

    AI_BUDGET_DAILY_USD: float | None = Field(
        default=None, description="Default daily AI cost budget in USD. None means unlimited"
    )

    AI_BUDGET_MODE: str = Field(default="soft", description="AI budget mode: soft or hard")

    AI_PROVIDERS: dict[str, dict[str, Any]] = Field(
        default_factory=get_default_provider_registry,
        description="AI provider registry keyed by provider name",
    )

    STRATEGY_SCORE_MODEL_VERSION: str = Field(
        default="v1", description="Model version for strategy score outputs"
    )

    STRATEGY_SCORE_WEIGHTS: dict[str, float] = Field(
        default_factory=lambda: {
            "profitability": 0.2,
            "risk_control": 0.2,
            "stability": 0.2,
            "overfitting_risk": 0.15,
            "executability": 0.15,
            "benchmark_comparison": 0.1,
        },
        description="Strategy score dimension weights",
    )

    @field_validator("AI_BUDGET_MODE")
    @classmethod
    def validate_ai_budget_mode(cls, v: str) -> str:
        normalized = str(v or "soft").strip().lower()
        supported_modes = {"soft", "hard"}
        if normalized not in supported_modes:
            raise ValueError(f"AI_BUDGET_MODE must be one of: {', '.join(sorted(supported_modes))}")
        return normalized

    @field_validator("AI_PROVIDERS", mode="before")
    @classmethod
    def validate_ai_providers(cls, v: object) -> dict[str, dict[str, Any]]:
        return parse_ai_providers(v)

    @field_validator("STRATEGY_SCORE_WEIGHTS", mode="before")
    @classmethod
    def validate_strategy_score_weights(cls, v: object) -> dict[str, float]:
        """Validate strategy score weights from dict or JSON string."""
        return parse_strategy_score_weights(v)
