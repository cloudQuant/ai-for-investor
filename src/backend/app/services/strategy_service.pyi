"""Static exports for the legacy runtime strategy-service module alias."""

from app.services.strategy.core import STRATEGIES_DIR as STRATEGIES_DIR
from app.services.strategy.core import StrategyService as StrategyService
from app.services.strategy.core import build_ai_strategy_draft as build_ai_strategy_draft
from app.services.strategy.core import get_all_strategy_templates as get_all_strategy_templates
from app.services.strategy.core import get_strategy_dir as get_strategy_dir
from app.services.strategy.core import get_strategy_readme as get_strategy_readme
from app.services.strategy.core import get_template_by_id as get_template_by_id
from app.services.strategy.core import (
    render_ai_strategy_draft_answer as render_ai_strategy_draft_answer,
)

__all__ = [
    "STRATEGIES_DIR",
    "StrategyService",
    "build_ai_strategy_draft",
    "get_all_strategy_templates",
    "get_strategy_dir",
    "get_strategy_readme",
    "get_template_by_id",
    "render_ai_strategy_draft_answer",
]
