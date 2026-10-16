"""Compile immutable AFI account-budget proposals for the shared Risk catalog.

This module only prepares policy drafts. The shared Risk ``policy_catalog``
owns immutable policy versions, and the account owner owns confirmation of the
exact published receipt. Nothing here publishes, activates, releases, or
replaces an existing account policy or reservation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from bt_api_risk.portfolio_analytics import FxObservationV1

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSIONED_POLICY_REF_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]*-v[1-9][0-9]*$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_BUDGET_KIND = "afi.static_account_budget"
_BUDGET_SCHEMA_VERSION = 1
_SUPPORTED_METRIC = "max_increase_notional"
_MAX_ACCOUNT_ALLOCATIONS = 256
_MAX_DECIMAL_DIGITS = 38
_MAX_DECIMAL_SCALE = 18
_MAX_BUDGET_FX_AGE_NS = 86_400_000_000_000  # One conservative 24-hour v1 window.


class RiskPolicyBudgetError(ValueError):
    """A finite validation error raised before any Risk catalog operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AccountBudgetAllocation:
    """One source-currency Risk notional cap assigned to an exact account."""

    account_ref: str
    amount: Decimal
    currency: str
    metric: str = _SUPPORTED_METRIC
    max_increase_count: int = 1


@dataclass(frozen=True, slots=True)
class StaticPortfolioBudgetPlan:
    """A single-valuation-currency, single-metric plan for one member version."""

    portfolio_ref: str
    membership_version: int
    membership_sha256: str
    currency: str
    total_amount: Decimal
    unallocated_amount: Decimal
    allocations: tuple[AccountBudgetAllocation, ...]
    metric: str = _SUPPORTED_METRIC


@dataclass(frozen=True, slots=True)
class AccountRiskPolicyDraft:
    """One detached catalog request for an account-scoped immutable version."""

    policy_ref: str
    account_ref: str
    _content_json: str = field(repr=False)

    def catalog_content(self) -> dict[str, object]:
        """Return a fresh JSON object suitable for ``policy.draft``."""

        content = json.loads(self._content_json)
        if type(content) is not dict:  # Defensive check for the private encoding.
            raise RiskPolicyBudgetError("INVALID_COMPILED_CONTENT")
        return content


@dataclass(frozen=True, slots=True)
class CompiledStaticPortfolioBudget:
    """Validated, deterministic set of account policy drafts for Risk catalog."""

    portfolio_ref: str
    membership_version: int
    allocation_set_sha256: str
    total_amount: str
    unallocated_amount: str
    currency: str
    metric: str
    drafts: tuple[AccountRiskPolicyDraft, ...]

    def catalog_requests(self) -> tuple[dict[str, object], ...]:
        """Return fresh ``policy.draft`` arguments in stable account order."""

        return tuple(
            {"policy_ref": draft.policy_ref, "content": draft.catalog_content()}
            for draft in self.drafts
        )


def compile_static_portfolio_budget(
    plan: StaticPortfolioBudgetPlan,
    *,
    policy_refs: Mapping[str, str],
    fx_observations: Mapping[str, FxObservationV1] | None = None,
) -> CompiledStaticPortfolioBudget:
    """Build per-account Risk policy drafts after strict conservation checks.

    The amount dimension is deliberately limited to Risk's
    ``max_increase_notional`` in one explicit valuation currency. Cross-
    currency members require source-bound Risk FX observations that are current
    and no older than the fixed 24-hour v1 limit. Conversion and conservation
    use exact rational arithmetic; mixed metrics and unpriced currencies fail
    before a caller can draft anything in the Risk catalog. ``unallocated``
    remains explicit, so converted limits plus withheld budget equal the
    declared portfolio total exactly.
    """

    if type(plan) is not StaticPortfolioBudgetPlan:
        raise RiskPolicyBudgetError("INVALID_PLAN")
    portfolio_ref = _identifier(plan.portfolio_ref, "INVALID_PORTFOLIO_REF")
    if type(plan.membership_version) is not int or plan.membership_version < 1:
        raise RiskPolicyBudgetError("INVALID_MEMBERSHIP_VERSION")
    if type(plan.membership_sha256) is not str or not _SHA256_RE.fullmatch(
        plan.membership_sha256
    ):
        raise RiskPolicyBudgetError("INVALID_MEMBERSHIP_DIGEST")
    currency = _currency(plan.currency)
    if plan.metric != _SUPPORTED_METRIC:
        raise RiskPolicyBudgetError("UNSUPPORTED_BUDGET_METRIC")
    if (
        type(plan.allocations) is not tuple
        or not plan.allocations
        or len(plan.allocations) > _MAX_ACCOUNT_ALLOCATIONS
    ):
        raise RiskPolicyBudgetError("INVALID_ALLOCATIONS")

    total_amount = _amount(plan.total_amount, "INVALID_TOTAL_AMOUNT")
    unallocated_amount = _amount(plan.unallocated_amount, "INVALID_UNALLOCATED_AMOUNT")
    if total_amount <= 0:
        raise RiskPolicyBudgetError("INVALID_TOTAL_AMOUNT")

    if fx_observations is None:
        fx_by_currency: Mapping[str, FxObservationV1] = {}
    elif isinstance(fx_observations, Mapping) and all(
        type(key) is str for key in fx_observations
    ):
        fx_by_currency = fx_observations
    else:
        raise RiskPolicyBudgetError("INVALID_BUDGET_FX_FACTS")

    normalized: list[
        tuple[AccountBudgetAllocation, str, str, str, str, dict[str, object] | None]
    ] = []
    seen_accounts: set[str] = set()
    required_fx_currencies: set[str] = set()
    now_ns: int | None = None
    for allocation in plan.allocations:
        if type(allocation) is not AccountBudgetAllocation:
            raise RiskPolicyBudgetError("INVALID_ALLOCATION")
        account_ref = _identifier(allocation.account_ref, "INVALID_ACCOUNT_REF")
        if account_ref in seen_accounts:
            raise RiskPolicyBudgetError("DUPLICATE_ACCOUNT")
        seen_accounts.add(account_ref)
        if allocation.metric != plan.metric:
            raise RiskPolicyBudgetError("MIXED_BUDGET_METRIC")
        source_currency = _currency(allocation.currency)
        source_amount = _amount(allocation.amount, "INVALID_ALLOCATION_AMOUNT")
        if source_amount <= 0:
            raise RiskPolicyBudgetError("INVALID_ALLOCATION_AMOUNT")
        if (
            type(allocation.max_increase_count) is not int
            or allocation.max_increase_count < 0
        ):
            raise RiskPolicyBudgetError("INVALID_INCREASE_COUNT")

        fx_payload: dict[str, object] | None = None
        if source_currency == currency:
            if source_currency in fx_by_currency:
                raise RiskPolicyBudgetError("UNEXPECTED_BUDGET_FX_FACT")
            amount = source_amount
        else:
            required_fx_currencies.add(source_currency)
            fx_observation = fx_by_currency.get(source_currency)
            if type(fx_observation) is not FxObservationV1:
                raise RiskPolicyBudgetError("BUDGET_FX_REQUIRED")
            if (
                fx_observation.base_currency != source_currency
                or fx_observation.quote_currency != currency
                or fx_observation.direction != "BASE_TO_QUOTE"
                or fx_observation.rate_unit != "QUOTE_PER_BASE"
            ):
                raise RiskPolicyBudgetError("BUDGET_FX_PAIR_MISMATCH")
            if now_ns is None:
                now_ns = time.time_ns()
                if type(now_ns) is not int or now_ns <= 0:
                    raise RiskPolicyBudgetError("INVALID_BUDGET_FX_CLOCK")
            if not fx_observation.as_of_ns <= now_ns < fx_observation.valid_until_ns:
                raise RiskPolicyBudgetError("BUDGET_FX_NOT_CURRENT")
            if now_ns - fx_observation.as_of_ns > _MAX_BUDGET_FX_AGE_NS:
                raise RiskPolicyBudgetError("BUDGET_FX_STALE")
            rate = _amount(fx_observation.rate, "INVALID_BUDGET_FX_RATE")
            if rate <= 0:
                raise RiskPolicyBudgetError("INVALID_BUDGET_FX_RATE")
            amount = _amount(
                _fraction_as_decimal(Fraction(source_amount) * Fraction(rate)),
                "INVALID_CONVERTED_ALLOCATION_AMOUNT",
            )
            if amount <= 0:
                raise RiskPolicyBudgetError("INVALID_CONVERTED_ALLOCATION_AMOUNT")
            fx_payload = _fx_observation_payload(fx_observation, rate)

        normalized.append(
            (
                allocation,
                account_ref,
                _decimal_text(source_amount),
                source_currency,
                _decimal_text(amount),
                fx_payload,
            )
        )

    if set(fx_by_currency) != required_fx_currencies:
        if required_fx_currencies - set(fx_by_currency):
            raise RiskPolicyBudgetError("BUDGET_FX_REQUIRED")
        raise RiskPolicyBudgetError("UNEXPECTED_BUDGET_FX_FACT")

    if not isinstance(policy_refs, Mapping):
        raise RiskPolicyBudgetError("INVALID_POLICY_REFS")
    if any(type(account_ref) is not str for account_ref in policy_refs):
        raise RiskPolicyBudgetError("INVALID_POLICY_REFS")
    if set(policy_refs) != seen_accounts:
        raise RiskPolicyBudgetError("POLICY_REF_ACCOUNT_SET_MISMATCH")

    refs_by_account: dict[str, str] = {}
    seen_refs: set[str] = set()
    for account_ref, policy_ref in policy_refs.items():
        if (
            type(policy_ref) is not str
            or len(policy_ref) > 128
            or not _VERSIONED_POLICY_REF_RE.fullmatch(policy_ref)
        ):
            raise RiskPolicyBudgetError("VERSIONED_POLICY_REF_REQUIRED")
        if policy_ref in seen_refs:
            raise RiskPolicyBudgetError("DUPLICATE_POLICY_REF")
        seen_refs.add(policy_ref)
        refs_by_account[account_ref] = policy_ref

    all_amounts = [total_amount, unallocated_amount] + [
        _amount(amount_text, "INVALID_CONVERTED_ALLOCATION_AMOUNT")
        for _, _, _, _, amount_text, _ in normalized
    ]
    scale = max(max(0, -amount.as_tuple().exponent) for amount in all_amounts)
    conserved_units = sum(_amount_units(amount, scale) for amount in all_amounts[1:])
    if conserved_units != _amount_units(total_amount, scale):
        raise RiskPolicyBudgetError("BUDGET_NOT_CONSERVED")

    manifest_allocations = [
        {
            "account_ref": account_ref,
            "policy_ref": refs_by_account[account_ref],
            "amount": amount_text,
            "source_amount": source_amount_text,
            "source_currency": source_currency,
            "fx_observation": fx_payload,
            "max_increase_count": allocation.max_increase_count,
            "metric": allocation.metric,
            "currency": currency,
        }
        for allocation, account_ref, source_amount_text, source_currency, amount_text, fx_payload in sorted(
            normalized, key=lambda row: row[1]
        )
    ]
    allocation_manifest = {
        "kind": _BUDGET_KIND,
        "schema_version": _BUDGET_SCHEMA_VERSION,
        "portfolio_ref": portfolio_ref,
        "membership_version": plan.membership_version,
        "membership_sha256": plan.membership_sha256,
        "metric": plan.metric,
        "currency": currency,
        "total_amount": _decimal_text(total_amount),
        "unallocated_amount": _decimal_text(unallocated_amount),
        "allocations": manifest_allocations,
    }
    allocation_set_sha256 = _canonical_sha256(allocation_manifest)

    drafts: list[AccountRiskPolicyDraft] = []
    for (
        allocation,
        account_ref,
        source_amount_text,
        source_currency,
        amount_text,
        fx_payload,
    ) in sorted(normalized, key=lambda row: row[1]):
        policy_ref = refs_by_account[account_ref]
        risk_policy = {
            "policy_id": policy_ref,
            "max_increase_notional": amount_text,
            "max_increase_count": allocation.max_increase_count,
            "permit_ttl_seconds": 30.0,
            "require_strategy_allocation": False,
            "notional_unit": currency,
        }
        content = {
            "afi_budget": {
                "kind": _BUDGET_KIND,
                "schema_version": _BUDGET_SCHEMA_VERSION,
                "portfolio_ref": portfolio_ref,
                "membership_version": plan.membership_version,
                "membership_sha256": plan.membership_sha256,
                "allocation_set_sha256": allocation_set_sha256,
                "metric": plan.metric,
                "currency": currency,
                "total_amount": _decimal_text(total_amount),
                "unallocated_amount": _decimal_text(unallocated_amount),
                "account_ref": account_ref,
                "source_amount": source_amount_text,
                "source_currency": source_currency,
                "allocated_amount": amount_text,
                "fx_observation": fx_payload,
            },
            "risk_policy": risk_policy,
        }
        drafts.append(
            AccountRiskPolicyDraft(
                policy_ref=policy_ref,
                account_ref=account_ref,
                _content_json=_canonical_json(content),
            )
        )

    return CompiledStaticPortfolioBudget(
        portfolio_ref=portfolio_ref,
        membership_version=plan.membership_version,
        allocation_set_sha256=allocation_set_sha256,
        total_amount=_decimal_text(total_amount),
        unallocated_amount=_decimal_text(unallocated_amount),
        currency=currency,
        metric=plan.metric,
        drafts=tuple(drafts),
    )


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise RiskPolicyBudgetError(code)
    return value


def _currency(value: object) -> str:
    if type(value) is not str or not _CURRENCY_RE.fullmatch(value):
        raise RiskPolicyBudgetError("INVALID_CURRENCY")
    return value


def _amount(value: object, code: str) -> Decimal:
    if type(value) is Decimal:
        amount = value
    elif type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise RiskPolicyBudgetError(code) from None
    else:
        # Floats and integers are rejected so the caller must supply an exact
        # decimal value or its unambiguous base-10 string representation.
        raise RiskPolicyBudgetError(code)
    if not amount.is_finite() or amount < 0:
        raise RiskPolicyBudgetError(code)
    if amount == 0:
        return Decimal("0")
    parts = amount.as_tuple()
    if (
        len(parts.digits) > _MAX_DECIMAL_DIGITS
        or -parts.exponent > _MAX_DECIMAL_SCALE
        or amount.adjusted() > 63
    ):
        raise RiskPolicyBudgetError(code)
    if len(format(amount, "f")) > 64:
        raise RiskPolicyBudgetError(code)
    return amount


def _decimal_text(amount: Decimal) -> str:
    if amount == 0:
        return "0"
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _amount_units(amount: Decimal, scale: int) -> int:
    """Convert a validated Decimal to exact integer units without context rounding."""

    if amount == 0:
        return 0
    sign, digits, exponent = amount.as_tuple()
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    if sign:
        coefficient = -coefficient
    return coefficient * (10 ** (exponent + scale))


def _fraction_as_decimal(value: Fraction) -> Decimal:
    """Convert a finite base-10 rational to Decimal without context rounding."""

    numerator = value.numerator
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise RiskPolicyBudgetError("NON_TERMINATING_BUDGET_FX_RESULT")
    scale = max(twos, fives)
    coefficient = numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    sign = 1 if coefficient < 0 else 0
    digits_text = str(abs(coefficient))
    digits = tuple(int(character) for character in digits_text)
    return Decimal((sign, digits, -scale))


def _fx_observation_payload(
    observation: FxObservationV1,
    rate: Decimal,
) -> dict[str, object]:
    """Keep the exact source and freshness facts in the immutable policy draft."""

    return {
        "observation_ref": observation.observation_ref,
        "base_currency": observation.base_currency,
        "quote_currency": observation.quote_currency,
        "direction": observation.direction,
        "rate_unit": observation.rate_unit,
        "rate": _decimal_text(rate),
        "as_of_ns": observation.as_of_ns,
        "valid_until_ns": observation.valid_until_ns,
        "source_ref": observation.source_ref,
        "source_version": observation.source_version,
        "source_generation": observation.source_generation,
        "source_cursor": observation.source_cursor,
    }


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise RiskPolicyBudgetError("INVALID_COMPILED_CONTENT") from None


def _canonical_sha256(value: object) -> str:
    encoded = _canonical_json(value).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AccountBudgetAllocation",
    "AccountRiskPolicyDraft",
    "CompiledStaticPortfolioBudget",
    "RiskPolicyBudgetError",
    "StaticPortfolioBudgetPlan",
    "compile_static_portfolio_budget",
]
