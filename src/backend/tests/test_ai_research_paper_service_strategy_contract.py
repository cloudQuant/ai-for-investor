"""Narrow source checks for AI-paper ServiceExecution opt-in and order metadata."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config as app_config
from app.services import ai_research_provenance, workspace_unit_runtime
from app.services.live_trading import manager as manager_module
from app.services.live_trading.service_execution_launch import (
    AI_RESEARCH_SERVICE_INTENT_CONTRACT_REF,
    SERVER_ATTESTED_AI_RESEARCH_STRATEGY_ID,
    SERVICE_EXECUTION_AI_RESEARCH_PROFILE_ENV,
    SERVICE_EXECUTION_INSTANCE_ENV,
    SERVICE_EXECUTION_PAPER_RUNTIME_DIGEST_ENV,
    SERVICE_EXECUTION_PROFILE_ENV,
    SERVICE_EXECUTION_PROFILE_MAP_ENV,
    SERVICE_EXECUTION_RUN_ENV,
    SERVICE_EXECUTION_STRATEGY_ENV,
    SERVICE_EXECUTION_SUBJECT_ENV,
    ServiceStrategyProfileError,
    ServiceStrategyProfileRegistry,
    TrustedServiceStrategyProfile,
    _validate_server_attested_ai_research_strategy_source,
)

_PROFILE_REF = "afi-test-ai-paper-profile"
_SUBJECT_REF = "subject.ai-paper-source-test"
_STRATEGY_ID = "strategy.ai-paper-source-test"
_INSTANCE_ID = "instance.ai-paper-source-test"
_OWNER_KEYS = ("manual:OKX:synthetic-ai-paper-account",)


def _profile() -> TrustedServiceStrategyProfile:
    return TrustedServiceStrategyProfile(
        profile_ref=_PROFILE_REF,
        strategy_id=SERVER_ATTESTED_AI_RESEARCH_STRATEGY_ID,
        script_sha256=hashlib.sha256(
            workspace_unit_runtime._UNIT_RUN_PY.encode("utf-8")
        ).hexdigest(),
        strategy_ref="strategy.synthetic.ai-paper-owner",
        account_ref="account.synthetic.ai-paper-owner",
        principal_ref="principal.synthetic.ai-paper-owner",
        owner_profile_ref="owner.synthetic.ai-paper-owner",
        intent_contract_ref=AI_RESEARCH_SERVICE_INTENT_CONTRACT_REF,
        service_id="service.synthetic.ai-paper-owner",
        service_instance_id="instance.synthetic.ai-paper-owner",
        transport_ref="transport.synthetic.ai-paper-owner",
        orders_scope_ref="scope.synthetic.ai-paper-orders",
        order_query_scope_ref="scope.synthetic.ai-paper-query",
        authorized_subjects=frozenset({_SUBJECT_REF}),
        legacy_gateway_keys=_OWNER_KEYS,
        orders_operations=frozenset({"orders.submit", "orders.cancel"}),
        order_query_operations=frozenset({"orders.query"}),
        client_config_factory=lambda _context: {},
        runtime_factory=lambda _config, _context: object(),
        server_attested_ai_research_strategy_ids=True,
    )


def _runtime_tree(runtime_dir: Path, strategy_source: str) -> Path:
    runtime_dir.mkdir()
    (runtime_dir / "run.py").write_text(
        workspace_unit_runtime._UNIT_RUN_PY,
        encoding="utf-8",
    )
    (runtime_dir / "strategy_ai_paper.py").write_text(
        strategy_source,
        encoding="utf-8",
    )
    (runtime_dir / "config.yaml").write_text(
        "workspace_unit:\n"
        "  strategy_module: strategy_ai_paper.py\n"
        "  template_dir: synthetic-template\n",
        encoding="utf-8",
    )
    return runtime_dir / "run.py"


def _managed_strategy_source(*, omit: str | None = None) -> str:
    fields = {
        "managed_intent_id": '"intent.ai-paper.1"',
        "managed_signal_id": '"signal.ai-paper.1"',
        "managed_instrument": '"PAPER:SIM:BTC-USDT"',
        "managed_position_effect": '"OPEN"',
        "managed_metadata_version": '"bt-cerebro-fill-metadata-r1"',
        "reduce_only": "False",
    }
    fields.pop(omit, None)
    keywords = ",\n                ".join(f"{name}={value}" for name, value in fields.items())
    return (
        f'AFI_SERVICE_INTENT_CONTRACT_REF = "{AI_RESEARCH_SERVICE_INTENT_CONTRACT_REF}"\n'
        "\n"
        "class Strategy:\n"
        "    def next(self):\n"
        "        self.buy(\n"
        f"                {keywords}\n"
        "        )\n"
    )


def test_attested_paper_strategy_requires_bound_managed_order_metadata(tmp_path) -> None:
    profile = _profile()
    run_path = _runtime_tree(
        tmp_path / "runtime",
        _managed_strategy_source(),
    )
    runtime_digest = ai_research_provenance.ai_research_paper_materialized_runtime_digest(
        run_path.parent
    )
    assert runtime_digest is not None
    source_digest = _validate_server_attested_ai_research_strategy_source(
        profile,
        run_path,
        runtime_digest,
    )
    assert source_digest == hashlib.sha256(
        (run_path.parent / "strategy_ai_paper.py").read_bytes()
    ).hexdigest()

    (run_path.parent / "strategy_ai_paper.py").write_text(
        _managed_strategy_source(omit="managed_metadata_version"),
        encoding="utf-8",
    )
    updated_runtime_digest = ai_research_provenance.ai_research_paper_materialized_runtime_digest(
        run_path.parent
    )
    assert updated_runtime_digest is not None
    with pytest.raises(ServiceStrategyProfileError) as raised:
        _validate_server_attested_ai_research_strategy_source(
            profile,
            run_path,
            updated_runtime_digest,
        )
    assert raised.value.code == "PAPER_STRATEGY_MANAGED_ORDER_CONTRACT_REQUIRED"


def test_ai_paper_profile_requires_manager_server_attestation_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _profile()
    registry = ServiceStrategyProfileRegistry((profile,))
    instance = {
        "id": _INSTANCE_ID,
        "user_id": _SUBJECT_REF,
        "strategy_id": _STRATEGY_ID,
    }
    assert registry.resolve_for_instance(instance, run_id="run.synthetic") is None
    selected = registry.resolve_for_instance(
        instance,
        run_id="run.synthetic",
        allow_server_attested_ai_research_strategy_ids=True,
    )
    assert selected is not None
    assert selected[0] is profile
    assert selected[1].strategy_id == _STRATEGY_ID

    monkeypatch.setenv(SERVICE_EXECUTION_AI_RESEARCH_PROFILE_ENV, _PROFILE_REF)
    monkeypatch.setenv(
        SERVICE_EXECUTION_PROFILE_MAP_ENV,
        json.dumps({_STRATEGY_ID: _PROFILE_REF}),
    )
    monkeypatch.setattr(
        manager_module,
        "get_service_strategy_profile_registry",
        lambda _refs: registry,
    )
    monkeypatch.setattr(manager_module, "validate_profile_owner_grant", lambda *_args: None)
    monkeypatch.setattr(
        manager_module,
        "legacy_gateway_exclusions",
        lambda: frozenset(_OWNER_KEYS),
    )
    monkeypatch.setattr(
        manager_module,
        "validate_profile_strategy_source",
        lambda _profile, _path: "source",
    )
    monkeypatch.setattr(
        app_config,
        "get_settings",
        lambda: SimpleNamespace(SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON="{}"),
    )

    manager = object.__new__(manager_module.LiveTradingManager)
    manager._gateway_lock = threading.RLock()
    manager._gateways = {}
    normal_instance = {
        **instance,
        "_server_execution_mode": "live",
        "_server_allow_service_strategy_execution": True,
    }
    with pytest.raises(ServiceStrategyProfileError) as untrusted:
        manager._service_strategy_launch(normal_instance, tmp_path)
    assert untrusted.value.code == "STRATEGY_PROFILE_MAPPING_MISMATCH"

    attested_instance = {
        **normal_instance,
        manager_module._SERVER_ATTESTED_PAPER_RUNTIME_FIELD: True,
        manager_module._SERVER_ATTESTED_PAPER_RUNTIME_DIGEST_FIELD: "a" * 64,
    }
    resolved = manager._service_strategy_launch(attested_instance, tmp_path)
    assert resolved is not None
    assert resolved[0] is profile
    assert resolved[1].strategy_id == _STRATEGY_ID

    # The child-side launch context also requires the signed runtime digest;
    # merely selecting the installed profile is not sufficient.
    environment = {
        SERVICE_EXECUTION_PROFILE_ENV: _PROFILE_REF,
        SERVICE_EXECUTION_INSTANCE_ENV: _INSTANCE_ID,
        SERVICE_EXECUTION_SUBJECT_ENV: _SUBJECT_REF,
        SERVICE_EXECUTION_STRATEGY_ENV: _STRATEGY_ID,
        SERVICE_EXECUTION_RUN_ENV: "run.synthetic",
        SERVICE_EXECUTION_PAPER_RUNTIME_DIGEST_ENV: "a" * 64,
    }
    child_profile, child_context = registry.context_from_environment(environment)
    assert child_profile is profile
    assert child_context.strategy_id == _STRATEGY_ID
    environment.pop(SERVICE_EXECUTION_PAPER_RUNTIME_DIGEST_ENV)
    with pytest.raises(ServiceStrategyProfileError) as missing_digest:
        registry.context_from_environment(environment)
    assert missing_digest.value.code == "LAUNCH_CONTEXT_NOT_AUTHORIZED"
