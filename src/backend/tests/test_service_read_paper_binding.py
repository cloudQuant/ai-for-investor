from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.service_read.contracts import ServiceReadContractError
from app.services.service_read.deployment import (
    ServiceReadDeploymentError,
    _parse_paper_submit_bindings,
)


class _PaperDomain:
    fingerprint = "d" * 64
    simulation_account_ref = "simulation-account-1"
    execution_domain_ref = "paper-domain-1"
    strategy_ref = "strategy-1"
    experiment_ref = "experiment-1"
    model_ref = "paper-matching-v1"
    model_version = "1"
    quote_source_ref = "synthetic-quotes-v1"
    cash_currency = "USD"
    initial_cash = 100_000
    initial_fees = 0
    fee_rate = 0.001
    fee_quantum = 0.01
    max_quote_age_ns = 30_000_000_000
    instruments = (SimpleNamespace(instrument="BTCUSDT", metadata_version="instrument-v7"),)
    opening_positions = ()

    @classmethod
    def from_payload(cls, _payload):
        return cls()

    def validate_binding(self, _wire_scope, _execution_scope):
        return None


class _ExecutionScope:
    def __init__(self, provider, environment, account_ref, strategy_id, trading_day):
        self.provider = provider
        self.environment = environment
        self.account_ref = account_ref
        self.strategy_id = strategy_id
        self.trading_day = trading_day


def _wire_scope():
    return SimpleNamespace(
        execution_domain_ref="paper-domain-1",
        account_ref="simulation-account-1",
        account_refs=(),
        strategy_ref="strategy-1",
        run_id=None,
        manual_book_ref=None,
        portfolio_ref=None,
        group_id=None,
        leg_id=None,
    )


def _paper_config(**overrides):
    result = {
        "control_mode": "execution_only",
        "mount": "application.orders",
        "scope_ref": "paper-submit-scope",
        "query_scope_ref": "paper-query-scope",
        "account_ref": "simulation-account-1",
        "execution_domain_ref": "paper-domain-1",
        "strategy_ref": "strategy-1",
        "paper_owner_domain": {},
        "execution_scope": {
            "provider": "paper",
            "environment": "paper",
            "account_ref": "simulation-account-1",
            "strategy_id": "strategy-1",
            "trading_day": None,
        },
    }
    result.update(overrides)
    return result


def _parse(raw):
    submit_scope = _wire_scope()
    query_scope = _wire_scope()
    return _parse_paper_submit_bindings(
        raw,
        {"paper-submit-scope": submit_scope, "paper-query-scope": query_scope},
        {"paper-query-scope": object()},
        {
            "PaperOwnerDomainV1": _PaperDomain,
            "ExecutionScope": _ExecutionScope,
            "PAPER_PROVIDER": "paper",
            "PAPER_ENVIRONMENT": "paper",
        },
    )


def test_paper_binding_requires_and_records_explicit_execution_only_mode():
    bindings = _parse({"legacy-account-1": _paper_config()})

    assert bindings["legacy-account-1"].control_mode == "execution_only"


def test_paper_binding_exposes_cutover_facts_from_its_typed_owner_domain():
    binding = _parse({"legacy-account-1": _paper_config()})["legacy-account-1"]

    assert binding.paper_domain_sha256 == "d" * 64
    assert binding.experiment_ref == "experiment-1"
    assert binding.model_ref == "paper-matching-v1"
    assert binding.model_version == "1"
    assert binding.quote_source_ref == "synthetic-quotes-v1"
    assert binding.cash_currency == "USD"
    assert binding.initial_cash == 100_000
    assert binding.initial_fees == 0
    assert binding.fee_rate == 0.001
    assert binding.fee_quantum == 0.01
    assert binding.max_quote_age_ns == 30_000_000_000
    assert binding.instrument_metadata_versions == {"BTCUSDT": "instrument-v7"}
    assert binding.opening_positions == ()


@pytest.mark.parametrize(
    "mode", ["execution_only", "execution_risk", "execution_risk_monitor"]
)
def test_paper_binding_accepts_only_the_three_server_owned_composition_modes(mode: str):
    binding = _parse({"legacy-account-1": _paper_config(control_mode=mode)})[
        "legacy-account-1"
    ]

    assert binding.control_mode == mode


@pytest.mark.parametrize(
    "mode", ["risk", "monitor", "risk_and_monitor", "execution_with_monitor"]
)
def test_paper_binding_rejects_unregistered_composition_modes(mode: str):
    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse({"legacy-account-1": _paper_config(control_mode=mode)})

    assert error.value.code == "PAPER_RISK_MONITOR_UNSUPPORTED"


def test_paper_typed_binding_rejects_non_string_or_unlisted_mode():
    binding = _parse({"legacy-account-1": _paper_config()})["legacy-account-1"]

    for invalid_mode in ([], "execution_risk_monitor_extra"):
        with pytest.raises(ServiceReadContractError) as error:
            replace(binding, control_mode=invalid_mode)

        assert error.value.code == "INVALID_PAPER_CONTROL_MODE"


def test_paper_binding_rejects_an_unknown_control_mode():
    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse({"legacy-account-1": _paper_config(control_mode="automatic")})

    assert error.value.code == "INVALID_PAPER_CONTROL_MODE"


@pytest.mark.parametrize(
    "field",
    [
        "risk_policy_ref",
        "risk_binding_ref",
        "risk_mode",
        "risk_enabled",
        "monitor_ingress_ref",
        "monitor_binding_ref",
        "monitor_mode",
    ],
)
def test_paper_binding_refuses_unwired_risk_or_monitor_selectors(field: str):
    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse({"legacy-account-1": _paper_config(**{field: "not-wired"})})

    assert error.value.code == "PAPER_RISK_MONITOR_UNSUPPORTED"


def test_paper_binding_rejects_implicit_execution_only_default():
    config = _paper_config()
    config.pop("control_mode")

    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse({"legacy-account-1": config})

    assert error.value.code == "PAPER_CONTROL_MODE_REQUIRED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("controls", ["risk"]),
        ("required_controls", ["monitor"]),
        ("enabled_components", ["execution", "risk"]),
    ],
)
def test_paper_binding_rejects_risk_or_monitor_component_lists(field: str, value: list[str]):
    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse({"legacy-account-1": _paper_config(**{field: value})})

    assert error.value.code == "PAPER_RISK_MONITOR_UNSUPPORTED"
