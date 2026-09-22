from importlib import import_module

from app.services.strategy import core


def test_legacy_strategy_service_aliases_core_exports() -> None:
    legacy_module = import_module("app.services.strategy_service")
    public_names = (
        "STRATEGIES_DIR",
        "StrategyService",
        "build_ai_strategy_draft",
        "get_all_strategy_templates",
        "get_strategy_dir",
        "get_strategy_readme",
        "get_template_by_id",
        "render_ai_strategy_draft_answer",
    )

    assert legacy_module is core
    assert tuple(core.__all__) == public_names
    for name in public_names:
        assert getattr(legacy_module, name) is getattr(core, name)
