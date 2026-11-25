"""Asset-specific raw snapshot quality checks extracted from plugin base."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from app.schemas.asset_research import RawAssetSnapshot
from app.services.asset_research.plugins.option.chain import (
    parse_option_chain_quality_policy,
    parse_option_chain_timestamp,
    validate_option_chain,
)
from app.services.asset_research.plugins.option.costs import parse_option_cost_snapshot
from app.services.asset_research.plugins.option.pricing import solve_implied_volatility


class AssetQualityPluginProtocol(Protocol):
    """Subset of plugin helper methods used by asset-specific quality gates."""

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]: ...

    @staticmethod
    def _present(value: object) -> bool: ...

    @staticmethod
    def _number(value: object) -> float | None: ...

    @staticmethod
    def _positive_number(value: object) -> bool: ...

    @classmethod
    def _valid_two_sided_quote(cls, quote: Mapping[str, Any]) -> bool: ...

    @classmethod
    def _quote_crossed(cls, quote: Mapping[str, Any]) -> bool: ...

    def _option_pricing_input(
        self, snapshot: RawAssetSnapshot, option: Mapping[str, Any]
    ) -> tuple[Any, str | None]: ...

    def _crypto_market_quality_feature_values(
        self, crypto: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


QualityCheckResult = tuple[dict[str, bool | str | int | float | None], list[str]]


def _record_tristate_flag(
    checks: dict[str, bool | str | int | float | None],
    reasons: list[str],
    payload: Mapping[str, Any],
    *,
    source_key: str,
    check_key: str,
    reason_code: str,
    bad_value: bool,
) -> None:
    raw = payload.get(source_key)
    if raw is bad_value:
        checks[check_key] = False
        reasons.append(reason_code)
    else:
        checks[check_key] = None if raw is None else True


def _align_cutoff_timezone(cutoff_at: datetime, reference: datetime) -> datetime:
    if cutoff_at.tzinfo is None:
        return cutoff_at.replace(tzinfo=reference.tzinfo)
    return cutoff_at.astimezone(reference.tzinfo)


def check_bond_quality(
    plugin: AssetQualityPluginProtocol,
    snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate bond maturity, cashflows, curve, valuation, and disclosures."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    bond = plugin._mapping(fields.get("bond"))
    identity_details = snapshot.identity.details
    is_perpetual = (
        bond.get("is_perpetual") is True or getattr(identity_details, "is_perpetual", None) is True
    )
    checks["bond_maturity_present"] = is_perpetual or plugin._present(bond.get("maturity_date"))
    checks["bond_cashflows_present"] = plugin._present(bond.get("cashflows"))
    checks["bond_curve_present"] = plugin._present(bond.get("curve"))
    checks["bond_benchmark_present"] = plugin._present(bond.get("benchmark"))
    checks["bond_valuation_present"] = plugin._present(
        quote.get("official_valuation")
    ) or plugin._present(bond.get("official_valuation"))
    for check_key, reason_code in (
        ("bond_maturity_present", "BOND.MATURITY_MISSING"),
        ("bond_cashflows_present", "BOND.CASHFLOWS_MISSING"),
        ("bond_curve_present", "BOND.CURVE_MISSING"),
        ("bond_benchmark_present", "COMMON.BENCHMARK_MISSING"),
        ("bond_valuation_present", "COMMON.PRICE_UNAVAILABLE"),
    ):
        if not checks[check_key]:
            reasons.append(reason_code)
    if is_perpetual:
        reasons.append("BOND.PERPETUAL_MODEL_REQUIRED")
    has_executable_quote = plugin._valid_two_sided_quote(quote)
    checks["bond_executable_quote_present"] = has_executable_quote
    if checks["bond_valuation_present"] and not has_executable_quote:
        reasons.append("BOND.VALUATION_NOT_EXECUTABLE")
    _record_tristate_flag(
        checks,
        reasons,
        bond,
        source_key="evidence_coverage_low",
        check_key="bond_evidence_coverage_sufficient",
        reason_code="COMMON.EVIDENCE_COVERAGE_LOW",
        bad_value=True,
    )
    _record_tristate_flag(
        checks,
        reasons,
        bond,
        source_key="peer_data_complete",
        check_key="bond_peer_data_complete",
        reason_code="BOND.PEER_DATA_INCOMPLETE",
        bad_value=False,
    )
    _record_tristate_flag(
        checks,
        reasons,
        bond,
        source_key="credit_disclosure_current",
        check_key="bond_credit_disclosure_current",
        reason_code="BOND.CREDIT_DISCLOSURE_STALE",
        bad_value=False,
    )
    return checks, reasons


def check_fund_quality(
    plugin: AssetQualityPluginProtocol,
    _snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    _quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate fund NAV, benchmark, fee schedule, holdings currency, and track record."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    fund = plugin._mapping(fields.get("fund"))
    fund_type = str(fund.get("fund_type") or "").upper()
    checks["fund_type_present"] = bool(fund_type)
    checks["fund_official_nav_present"] = plugin._present(fund.get("official_nav"))
    checks["fund_benchmark_present"] = plugin._present(fund.get("benchmark"))
    checks["fund_fee_schedule_present"] = plugin._present(fund.get("fee_schedule"))
    checks["fund_holdings_as_of_present"] = plugin._present(fund.get("holdings_as_of"))
    for check_key, reason_code in (
        ("fund_type_present", "FUND.TYPE_UNKNOWN"),
        ("fund_official_nav_present", "FUND.OFFICIAL_NAV_MISSING"),
        ("fund_benchmark_present", "COMMON.BENCHMARK_MISSING"),
        ("fund_fee_schedule_present", "FUND.FEE_SCHEDULE_MISSING"),
        ("fund_holdings_as_of_present", "FUND.HOLDINGS_AS_OF_MISSING"),
    ):
        if not checks[check_key]:
            reasons.append(reason_code)
    _record_tristate_flag(
        checks,
        reasons,
        fund,
        source_key="holdings_stale",
        check_key="fund_holdings_current",
        reason_code="FUND.HOLDINGS_STALE",
        bad_value=True,
    )
    _record_tristate_flag(
        checks,
        reasons,
        fund,
        source_key="management_evidence_available",
        check_key="fund_management_evidence_available",
        reason_code="FUND.MANAGEMENT_EVIDENCE_LOW",
        bad_value=False,
    )
    _record_tristate_flag(
        checks,
        reasons,
        fund,
        source_key="secondary_market_data_complete",
        check_key="fund_secondary_market_data_complete",
        reason_code="FUND.SECONDARY_MARKET_DATA_PARTIAL",
        bad_value=False,
    )
    track_record_months = plugin._number(fund.get("track_record_months"))
    checks["fund_track_record_months"] = track_record_months
    if track_record_months is not None and track_record_months < 36:
        reasons.append("FUND.SHORT_TRACK_RECORD")
    return checks, reasons


def check_futures_quality(
    plugin: AssetQualityPluginProtocol,
    _snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate futures two-sided quote and term-structure completeness."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    futures = plugin._mapping(fields.get("futures"))
    checks["futures_bid_ask_present"] = plugin._valid_two_sided_quote(quote)
    if not checks["futures_bid_ask_present"]:
        reasons.append("FUTURES.BID_ASK_MISSING")
    elif plugin._quote_crossed(quote):
        reasons.append("FUTURES.QUOTE_INCONSISTENT")
    optional_quality_flags = {
        "term_structure_complete": "FUTURES.TERM_STRUCTURE_INCOMPLETE",
        "basis_alignment_complete": "FUTURES.BASIS_ALIGNMENT_PARTIAL",
        "market_context_current": "FUTURES.MARKET_CONTEXT_STALE",
        "broker_margin_available": "FUTURES.BROKER_MARGIN_UNKNOWN",
        "fundamental_coverage_complete": "FUTURES.FUNDAMENTAL_COVERAGE_LOW",
    }
    for field_name, reason_code in optional_quality_flags.items():
        value = futures.get(field_name)
        checks[f"futures_{field_name}"] = None if value is None else value is True
        if value is False:
            reasons.append(reason_code)
    return checks, reasons


def _check_option_contract_identity(
    checks: dict[str, bool | str | int | float | None],
    reasons: list[str],
    snapshot: RawAssetSnapshot,
) -> None:
    details = snapshot.identity.details
    option_contract_id = str(getattr(details, "option_contract_id", "") or "")
    exchange = str(getattr(details, "exchange", "") or "")
    last_trade_at = getattr(details, "last_trade_at", None)
    expiry_at = getattr(details, "expiry_at", None)
    checks["option_identity_exact"] = (
        snapshot.identity.identity_level == "CONTRACT"
        and bool(option_contract_id)
        and option_contract_id.upper() == snapshot.identity.identifier_value.upper()
        and bool(exchange)
        and (snapshot.identity.venue is None or exchange.upper() == snapshot.identity.venue.upper())
    )
    checks["option_last_trade_at_present"] = (
        isinstance(last_trade_at, datetime) and last_trade_at.tzinfo is not None
    )
    checks["option_contract_tradeable"] = None
    if not checks["option_identity_exact"]:
        reasons.append("OPTION.CONTRACT_IDENTITY_MISMATCH")
    if not isinstance(last_trade_at, datetime) or last_trade_at.tzinfo is None:
        reasons.append("OPTION.CONTRACT_LAST_TRADE_MISSING")
        return
    if not isinstance(expiry_at, datetime) or expiry_at.tzinfo is None:
        reasons.append("OPTION.CONTRACT_IDENTITY_REQUIRED")
        return
    cutoff_at = _align_cutoff_timezone(snapshot.cutoff_at, last_trade_at)
    checks["option_contract_tradeable"] = cutoff_at < last_trade_at and cutoff_at < expiry_at
    if not checks["option_contract_tradeable"]:
        reasons.append("OPTION.CONTRACT_NOT_TRADABLE")


def _check_option_chain_and_iv(
    plugin: AssetQualityPluginProtocol,
    checks: dict[str, bool | str | int | float | None],
    reasons: list[str],
    snapshot: RawAssetSnapshot,
    option: Mapping[str, Any],
    quote: Mapping[str, Any],
    pricing_input: Any,
    chain_records: object,
    chain_policy: Any,
    underlying_quote_at: datetime | None,
) -> None:
    if (
        isinstance(chain_records, list)
        and chain_policy is not None
        and underlying_quote_at is not None
        and pricing_input is not None
    ):
        details = snapshot.identity.details
        expiry_at = getattr(details, "expiry_at", None)
        option_right = getattr(details, "option_right", None)
        strike = plugin._number(getattr(details, "strike", None))
        if (
            not isinstance(expiry_at, datetime)
            or option_right not in {"CALL", "PUT"}
            or strike is None
        ):
            reasons.append("OPTION.CONTRACT_IDENTITY_REQUIRED")
        else:
            chain_quality = validate_option_chain(
                records=chain_records,
                pricing_template=pricing_input,
                cutoff_at=snapshot.cutoff_at,
                underlying_quote_at=underlying_quote_at,
                target_expiry_at=expiry_at,
                target_strike=strike,
                target_right=option_right,
                policy=chain_policy,
            )
            checks.update(chain_quality.checks)
            reasons.extend(chain_quality.reason_codes)

    if (
        pricing_input is not None
        and checks["option_bid_ask_present"]
        and not plugin._quote_crossed(quote)
    ):
        bid_result = solve_implied_volatility(
            replace(pricing_input, volatility=None),
            observed_price=float(quote["bid"]),
        )
        ask_result = solve_implied_volatility(
            replace(pricing_input, volatility=None),
            observed_price=float(quote["ask"]),
        )
        checks["option_bid_iv_solved"] = bid_result.implied_volatility is not None
        checks["option_ask_iv_solved"] = ask_result.implied_volatility is not None
        checks["option_bid_iv_reason"] = bid_result.reason_code or ""
        checks["option_ask_iv_reason"] = ask_result.reason_code or ""
        if bid_result.implied_volatility is None or ask_result.implied_volatility is None:
            reasons.append("OPTION.IV_SOLVER_FAILED")


def check_option_quality(
    plugin: AssetQualityPluginProtocol,
    snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate option contract identity, quote freshness, chain quality, and IV."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    option = plugin._mapping(fields.get("option"))
    _check_option_contract_identity(checks, reasons, snapshot)

    checks["option_contract_terms_present"] = plugin._present(option.get("contract_terms"))
    checks["option_bid_ask_present"] = plugin._valid_two_sided_quote(quote)
    pricing_input, pricing_input_reason = plugin._option_pricing_input(snapshot, option)
    checks["option_pricing_inputs_present"] = pricing_input is not None
    chain_records = option.get("chain")
    checks["option_chain_payload_present"] = isinstance(chain_records, list)
    chain_policy, chain_policy_reason = parse_option_chain_quality_policy(
        option.get("chain_quality_policy")
    )
    checks["option_chain_policy_present"] = chain_policy is not None
    cost_snapshot, cost_snapshot_reason = parse_option_cost_snapshot(option.get("cost_snapshot"))
    checks["option_cost_snapshot_present"] = cost_snapshot is not None
    underlying_quote_at = parse_option_chain_timestamp(option.get("underlying_quote_at"))
    checks["option_underlying_quote_timestamp_present"] = underlying_quote_at is not None
    option_quote_at = parse_option_chain_timestamp(quote.get("quote_at"))
    checks["option_quote_timestamp_present"] = option_quote_at is not None
    checks["option_quote_fresh"] = None
    checks["option_quote_synchronized"] = None

    if not checks["option_contract_terms_present"]:
        reasons.append("OPTION.CONTRACT_TERMS_MISSING")
    if not checks["option_bid_ask_present"]:
        reasons.append("OPTION.BID_ASK_MISSING")
    elif plugin._quote_crossed(quote):
        reasons.append("OPTION.QUOTE_INCONSISTENT")
    if pricing_input is None:
        reasons.append(pricing_input_reason or "OPTION.PRICING_INPUTS_MISSING")
    if not checks["option_chain_payload_present"]:
        reasons.append("OPTION.CHAIN_INCOMPLETE")
    if chain_policy is None:
        reasons.append(chain_policy_reason or "OPTION.CHAIN_POLICY_MISSING")
    if cost_snapshot is None:
        reasons.append(cost_snapshot_reason or "OPTION.COST_SNAPSHOT_MISSING")
    if underlying_quote_at is None:
        reasons.append("OPTION.CHAIN_UNDERLYING_TIMESTAMP_MISSING")
    if option_quote_at is None:
        reasons.append("OPTION.QUOTE_TIMESTAMP_MISSING")

    if chain_policy is not None and underlying_quote_at is not None and option_quote_at is not None:
        cutoff_at = _align_cutoff_timezone(snapshot.cutoff_at, option_quote_at)
        option_quote_age = (cutoff_at - option_quote_at).total_seconds()
        checks["option_quote_fresh"] = 0 <= option_quote_age <= chain_policy.max_quote_age_seconds
        checks["option_quote_synchronized"] = (
            abs((option_quote_at - underlying_quote_at).total_seconds())
            <= chain_policy.max_underlying_lag_seconds
        )
        if not checks["option_quote_fresh"]:
            reasons.append("OPTION.QUOTE_STALE")
        if not checks["option_quote_synchronized"]:
            reasons.append("OPTION.UNDERLYING_DESYNCHRONIZED")

    _check_option_chain_and_iv(
        plugin,
        checks,
        reasons,
        snapshot,
        option,
        quote,
        pricing_input,
        chain_records,
        chain_policy,
        underlying_quote_at,
    )
    optional_quality_flags = {
        "surface_coverage_complete": "OPTION.SURFACE_COVERAGE_INSUFFICIENT",
        "liquidity_adequate": "OPTION.LIQUIDITY_DEGRADED",
        "secondary_pricing_inputs_current": "OPTION.SECONDARY_PRICING_INPUTS_STALE",
    }
    for field_name, reason_code in optional_quality_flags.items():
        value = option.get(field_name)
        checks[f"option_{field_name}"] = None if value is None else value is True
        if value is False:
            reasons.append(reason_code)
    return checks, reasons


def check_fx_quality(
    plugin: AssetQualityPluginProtocol,
    snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate FX two-sided or reference quotes and macro/COT completeness."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    fx = plugin._mapping(fields.get("fx"))
    reference_quote = str(snapshot.source_manifest.get("quote_kind") or "").upper() == "REFERENCE"
    checks["fx_bid_ask_present"] = plugin._valid_two_sided_quote(quote)
    checks["fx_reference_quote"] = reference_quote
    checks["fx_completed_bar"] = fx.get("completed_bar") is True
    checks["fx_price_convention_present"] = plugin._present(fx.get("price_convention"))
    if not checks["fx_bid_ask_present"]:
        if not reference_quote:
            reasons.append("FX.BID_ASK_MISSING")
    elif plugin._quote_crossed(quote):
        reasons.append("FX.QUOTE_INCONSISTENT")
    if not checks["fx_completed_bar"]:
        reasons.append("FX.BAR_INCOMPLETE")
    if not checks["fx_price_convention_present"]:
        reasons.append("FX.PRICE_CONVENTION_UNKNOWN")
    optional_quality_flags = {
        "macro_available": "FX.MACRO_MISSING",
        "forward_points_available": "FX.FORWARD_POINTS_MISSING",
        "cot_available": "FX.COT_MISSING",
        "news_available": "FX.NEWS_COVERAGE_LOW",
        "history_sufficient": "FX.HISTORY_INSUFFICIENT",
    }
    for field_name, reason_code in optional_quality_flags.items():
        value = fx.get(field_name)
        checks[f"fx_{field_name}"] = None if value is None else value is True
        if value is False:
            reasons.append(reason_code)
    if fx.get("cross_source_warning") is True:
        checks["fx_cross_source_warning"] = True
        reasons.append("FX.CROSS_SOURCE_WARNING")
    else:
        checks["fx_cross_source_warning"] = (
            None if fx.get("cross_source_warning") is None else False
        )
    return checks, reasons


def check_crypto_quality(
    plugin: AssetQualityPluginProtocol,
    _snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Validate crypto venue verification, depth, multi-venue coverage, and market quality."""
    checks: dict[str, bool | str | int | float | None] = {}
    reasons: list[str] = []
    crypto = plugin._mapping(fields.get("crypto"))
    market_quality_features = plugin._crypto_market_quality_feature_values(crypto)
    checks["crypto_bid_ask_present"] = plugin._valid_two_sided_quote(quote)
    checks["crypto_venue_verified"] = crypto.get("venue_verified") is True
    checks["crypto_depth_1pct_present"] = plugin._positive_number(
        market_quality_features.get("depth_1pct", crypto.get("depth_1pct"))
    )
    if not checks["crypto_bid_ask_present"]:
        reasons.append("CRYPTO.QUOTE_UNAVAILABLE")
    elif plugin._quote_crossed(quote):
        reasons.append("CRYPTO.QUOTE_INCONSISTENT")
    if not checks["crypto_venue_verified"]:
        reasons.append("CRYPTO.VENUE_UNVERIFIED")
    if not checks["crypto_depth_1pct_present"]:
        reasons.append("CRYPTO.DEPTH_INSUFFICIENT")
    venue_count = plugin._number(
        market_quality_features.get(
            "composite_price_venue_count", crypto.get("composite_price_venue_count")
        )
    )
    checks["crypto_composite_price_venue_count"] = venue_count
    if venue_count is not None and venue_count < 2:
        reasons.append("CRYPTO.SINGLE_VENUE_REFERENCE")
    market_quality_reason = market_quality_features.get("crypto_market_quality_reason_code")
    checks["crypto_market_quality_reason"] = market_quality_reason
    if isinstance(market_quality_reason, str) and market_quality_reason not in {
        "CRYPTO.SINGLE_VENUE_REFERENCE"
    }:
        reasons.append(market_quality_reason)
    optional_quality_flags = {
        "history_sufficient": "CRYPTO.HISTORY_INSUFFICIENT",
        "token_migration_complete": "CRYPTO.TOKEN_MIGRATION_INCOMPLETE",
        "onchain_provider_supported": "CRYPTO.ONCHAIN_UNSUPPORTED",
        "secondary_market_metrics_complete": "CRYPTO.SECONDARY_METRICS_MISSING",
    }
    for field_name, reason_code in optional_quality_flags.items():
        value = crypto.get(field_name)
        checks[f"crypto_{field_name}"] = None if value is None else value is True
        if value is False:
            reasons.append(reason_code)
    return checks, reasons


_ASSET_QUALITY_CHECKERS: dict[
    str,
    Callable[
        [AssetQualityPluginProtocol, RawAssetSnapshot, Mapping[str, Any], Mapping[str, Any]],
        QualityCheckResult,
    ],
] = {
    "bond": check_bond_quality,
    "fund": check_fund_quality,
    "futures": check_futures_quality,
    "option": check_option_quality,
    "fx": check_fx_quality,
}


def dispatch_asset_quality_checks(
    plugin: AssetQualityPluginProtocol,
    asset_type: str,
    snapshot: RawAssetSnapshot,
    fields: Mapping[str, Any],
    quote: Mapping[str, Any],
) -> QualityCheckResult:
    """Route asset quality checks by ``asset_type``."""
    checker = _ASSET_QUALITY_CHECKERS.get(asset_type, check_crypto_quality)
    return checker(plugin, snapshot, fields, quote)
