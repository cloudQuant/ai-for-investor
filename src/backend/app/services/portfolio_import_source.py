"""Canonical source material contract for user-imported portfolio transactions."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

PORTFOLIO_IMPORT_SOURCE_SCHEMA_VERSION = 1
PORTFOLIO_IMPORT_SOURCE_MAX_ROWS = 10_000
PORTFOLIO_IMPORT_SOURCE_MAX_BYTES = 1_048_576


class PortfolioImportSourceError(ValueError):
    """A supplied source document or its integrity metadata is invalid."""


def build_portfolio_import_source_document(
    *,
    import_format: str,
    transactions: list[dict[str, Any]],
    source_as_of: str | None,
    source_currency: str | None,
) -> dict[str, Any]:
    """Build the immutable, JSON-native source document without deriving facts."""

    if not isinstance(import_format, str) or not import_format.strip() or len(import_format) > 20:
        raise PortfolioImportSourceError("import format is invalid")
    if not isinstance(transactions, list) or any(not isinstance(row, dict) for row in transactions):
        raise PortfolioImportSourceError("transactions must be a list of objects")
    if len(transactions) > PORTFOLIO_IMPORT_SOURCE_MAX_ROWS:
        raise PortfolioImportSourceError("transaction source contains too many rows")
    if source_as_of is not None:
        if not isinstance(source_as_of, str) or source_as_of != source_as_of.strip():
            raise PortfolioImportSourceError("source as-of date is invalid")
        try:
            parsed_date = date.fromisoformat(source_as_of)
        except ValueError as error:
            raise PortfolioImportSourceError("source as-of date is invalid") from error
        if parsed_date.isoformat() != source_as_of:
            raise PortfolioImportSourceError("source as-of date is invalid")
    if source_currency is not None:
        if (
            not isinstance(source_currency, str)
            or not 3 <= len(source_currency) <= 16
            or source_currency != source_currency.upper()
            or not source_currency.isascii()
            or not source_currency.isalnum()
        ):
            raise PortfolioImportSourceError("source currency is invalid")

    document = {
        "schema_version": PORTFOLIO_IMPORT_SOURCE_SCHEMA_VERSION,
        "format": import_format,
        "source_as_of": source_as_of,
        "source_currency": source_currency,
        "transactions": transactions,
    }
    source_bytes = canonical_portfolio_import_source_bytes(document)
    if len(source_bytes) > PORTFOLIO_IMPORT_SOURCE_MAX_BYTES:
        raise PortfolioImportSourceError("transaction source exceeds the size limit")
    return document


def canonical_portfolio_import_source_bytes(document: dict[str, Any]) -> bytes:
    """Return stable UTF-8 bytes for the stored JSON source document."""

    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as error:
        raise PortfolioImportSourceError("source document is not canonical JSON") from error


def portfolio_import_source_sha256(document: dict[str, Any]) -> str:
    """Hash the canonical source document representation."""

    return hashlib.sha256(canonical_portfolio_import_source_bytes(document)).hexdigest()


def verify_portfolio_import_source(
    *,
    document: Any,
    expected_sha256: str | None,
    expected_schema_version: int | None,
    import_format: str,
    imported_count: int,
    source_as_of: str | None,
    source_currency: str | None,
) -> bool:
    """Check stored metadata and source bytes without exposing invalid material."""

    if (
        type(expected_schema_version) is not int
        or expected_schema_version != PORTFOLIO_IMPORT_SOURCE_SCHEMA_VERSION
        or not isinstance(document, dict)
        or not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
    ):
        return False
    if (
        type(imported_count) is not int
        or type(document.get("schema_version")) is not int
        or document.get("schema_version") != expected_schema_version
        or document.get("format") != import_format
        or document.get("source_as_of") != source_as_of
        or document.get("source_currency") != source_currency
    ):
        return False
    transactions = document.get("transactions")
    if (
        not isinstance(transactions, list)
        or len(transactions) != imported_count
        or any(not isinstance(row, dict) for row in transactions)
    ):
        return False
    try:
        expected_document = build_portfolio_import_source_document(
            import_format=import_format,
            transactions=transactions,
            source_as_of=source_as_of,
            source_currency=source_currency,
        )
        return (
            document == expected_document
            and portfolio_import_source_sha256(document) == expected_sha256
        )
    except PortfolioImportSourceError:
        return False
