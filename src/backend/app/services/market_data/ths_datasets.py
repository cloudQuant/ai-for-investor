"""Canonical THS sourced A-share reference-series dataset definitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping

CANONICAL_STOCK_ADJUSTMENT_FACTORS_DATASET_CODE = "reference.stock_adjustment_factors"
CANONICAL_STOCK_FINANCIALS_INCOME_DATASET_CODE = "market.stock_financials_income"
CANONICAL_STOCK_FINANCIALS_BALANCE_DATASET_CODE = "market.stock_financials_balance"
CANONICAL_STOCK_FINANCIALS_CASHFLOW_DATASET_CODE = "market.stock_financials_cashflow"
CANONICAL_THS_REFERENCE_DATASET_CODES = (
    CANONICAL_STOCK_ADJUSTMENT_FACTORS_DATASET_CODE,
    CANONICAL_STOCK_FINANCIALS_INCOME_DATASET_CODE,
    CANONICAL_STOCK_FINANCIALS_BALANCE_DATASET_CODE,
    CANONICAL_STOCK_FINANCIALS_CASHFLOW_DATASET_CODE,
)

_CanonicalDatasetSpec = tuple[str, str, dict[str, object], list[str]]


def canonical_ths_reference_dataset_specs(
    primary_key_factory: Callable[[], list[str]],
) -> tuple[_CanonicalDatasetSpec, ...]:
    """Return THS datasets in their stable catalog-registration order."""
    return (
        (
            CANONICAL_STOCK_ADJUSTMENT_FACTORS_DATASET_CODE,
            "A-share adjustment factors reference series",
            _canonical_stock_adjustment_factors_schema(),
            primary_key_factory(),
        ),
        (
            CANONICAL_STOCK_FINANCIALS_INCOME_DATASET_CODE,
            "A-share income statement reference series",
            _canonical_stock_financials_income_schema(),
            primary_key_factory(),
        ),
        (
            CANONICAL_STOCK_FINANCIALS_BALANCE_DATASET_CODE,
            "A-share balance sheet reference series",
            _canonical_stock_financials_balance_schema(),
            primary_key_factory(),
        ),
        (
            CANONICAL_STOCK_FINANCIALS_CASHFLOW_DATASET_CODE,
            "A-share cash-flow statement reference series",
            _canonical_stock_financials_cashflow_schema(),
            primary_key_factory(),
        ),
    )


def _canonical_stock_adjustment_factors_schema() -> dict[str, object]:
    """Describe corporate-action adjustment factors as a sparse event series.

    The ``ex_date_ms`` source event time becomes the observation ``event_time``;
    ``dividend_per_share`` / ``per_share_bonus`` are the retained per-event
    fields.  This is deliberately not a daily bar grid: most days carry no event.
    """
    return _canonical_reference_series_schema(
        schema_version="reference-stock-adjustment-factors-v1",
        supported_asset_types=("stock",),
        observation_fields={
            "dividend_per_share": "decimal|null",
            "per_share_bonus": "decimal|null",
        },
    )


def _canonical_stock_financials_income_schema() -> dict[str, object]:
    """Describe A-share income statements as a multi-period reference series.

    Each observation's ``event_time`` is the reporting period end
    (``period_end_ms`` normalized to UTC midnight); ``fiscal_year`` /
    ``fiscal_period`` are retained as dimension fields alongside statement
    amounts.  ``null`` values mean "not disclosed for this period" and are
    passed through without zero-filling.
    """
    return _canonical_reference_series_schema(
        schema_version="market-stock-financials-income-v1",
        supported_asset_types=("stock",),
        observation_fields={
            "fiscal_year": "integer|null",
            "fiscal_period": "string|null",
            "operating_income": "decimal|null",
            "operating_costs": "decimal|null",
            "operating_profit": "decimal|null",
            "net_profit": "decimal|null",
            "parent_holder_net_profit": "decimal|null",
            "basic_eps": "decimal|null",
        },
    )


def _canonical_stock_financials_balance_schema() -> dict[str, object]:
    """Describe A-share balance sheets as a multi-period reference series."""
    return _canonical_reference_series_schema(
        schema_version="market-stock-financials-balance-v1",
        supported_asset_types=("stock",),
        observation_fields={
            "fiscal_year": "integer|null",
            "fiscal_period": "string|null",
            "assets_total": "decimal|null",
            "total_current_assets": "decimal|null",
            "total_debt": "decimal|null",
            "holder_equity_total": "decimal|null",
            "accounts_receivable": "decimal|null",
            "cash": "decimal|null",
        },
    )


def _canonical_stock_financials_cashflow_schema() -> dict[str, object]:
    """Describe A-share cash-flow statements as a multi-period reference series."""
    return _canonical_reference_series_schema(
        schema_version="market-stock-financials-cashflow-v1",
        supported_asset_types=("stock",),
        observation_fields={
            "fiscal_year": "integer|null",
            "fiscal_period": "string|null",
            "act_cash_flow_net": "decimal|null",
            "invest_cash_flow_net": "decimal|null",
            "financing_cash_flow_net": "decimal|null",
            "cash_equivalents_net_addition": "decimal|null",
        },
    )


def _canonical_reference_series_schema(
    *,
    schema_version: str,
    supported_asset_types: tuple[str, ...],
    observation_fields: Mapping[str, str],
) -> dict[str, object]:
    """Return an inert logical reference-series contract over the revision fact table."""
    return {
        "schema_version": schema_version,
        "data_kind": "reference_series",
        "supported_asset_types": list(supported_asset_types),
        "identity_fields": [
            "canonical_id",
            "asset_type",
            "market",
            "instrument_metadata_version",
        ],
        "series_dimensions": [
            "frequency",
            "adjustment",
            "price_basis",
            "currency",
            "unit",
            "source_policy_id",
        ],
        "observation_fields": {
            "event_time": "timestamp",
            "event_end": "timestamp|null",
            "available_at": "timestamp",
            **dict(observation_fields),
        },
        "provenance_fields": [
            "source_snapshot_id",
            "revision_number",
            "quality_status",
            "normalization_version",
        ],
    }
