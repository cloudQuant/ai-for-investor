"""Build persisted stock-daily report evidence at the task-execution boundary.

The report-save gate can only revalidate a vector that a producer wrote. This
module defines the narrow reader contract the task service calls, the producer
that persists the vector before the report is built, and the pure constructor
that turns one authorized publication read into the frozen
``StockDailyReportEvidenceVector``. It performs no I/O itself.

The vector carries only facts the reader actually returned. In particular, the
publication capture time is the snapshot's ``created_at`` and the observation
time is the single source observation time recorded on every row. A missing or
inconsistent value is rejected; it is never defaulted from a different field.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.stock_analysis import StockAnalysisTaskModel
from app.schemas.stock_analysis import (
    StockAnalysisParams,
    StockAnalysisStockDailySnapshotSelection,
)
from app.services.market_data.opendata_provider import OpendataPublishedSnapshotResult
from app.services.market_data.opendata_stock_daily_snapshot import (
    OpendataStockDailySnapshotError,
)
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RESEARCH_PURPOSE,
    StockAnalysisSnapshotAuthorizationReceipt,
)
from app.services.stock_analysis.stock_daily_report_evidence import (
    DATASET_ID,
    SOURCE_ID,
    StockDailyReportEvidence,
    StockDailyReportEvidenceError,
    StockDailyReportEvidenceVector,
    stock_daily_report_evidence_expectation,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    StockDailySnapshotAuthorizationError,
)

_UTC = timezone.utc
_POLICY_MARKET_BY_REQUEST_MARKET = {"CN-SSE": "SH", "CN-SZSE": "SZ"}
_SYMBOL = re.compile(r"[0-9]{6}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

EvidenceSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class StockDailyAuthorizedPublication:
    """One authorization-checked read of a pinned stock-daily publication.

    ``result`` is exactly what the OpenData reader validated for the pinned
    publication; ``receipt`` is the ALLOW decision that preceded that read.
    Both are required: neither the snapshot nor the receipt alone is evidence.
    """

    result: OpendataPublishedSnapshotResult
    receipt: StockAnalysisSnapshotAuthorizationReceipt


class StockDailyReportEvidenceReader(Protocol):
    """Authorization-aware reader the task service calls before report save.

    Implementations must read exactly the selected publication for ``user_id``
    and must fail closed on a missing grant, an expired or revoked grant, or an
    unsupported coverage claim. The service never supplies a fallback reader.
    """

    async def read_authorized(
        self,
        *,
        selector: StockAnalysisStockDailySnapshotSelection,
        user_id: str,
        session: AsyncSession,
    ) -> StockDailyAuthorizedPublication:
        """Read one pinned publication under the current user's grants."""
        ...


class StockDailyReportEvidenceProducerHost(Protocol):
    """Task-service surface used by the producer at execution start."""

    stock_daily_snapshot_reader: StockDailyReportEvidenceReader | None
    evidence_session_factory: EvidenceSessionFactory


async def produce_report_evidence(
    host: StockDailyReportEvidenceProducerHost,
    task: StockAnalysisTaskModel,
    params: StockAnalysisParams,
) -> None:
    """Persist the declared stock-daily vector before the report is built.

    Legacy tasks declare no selector, so this function never opens a reader.
    A declared selector whose vector is already present is left untouched: the
    save-time gate remains the only revalidation point. Otherwise the injected
    reader performs exactly one authorization-aware read and the returned
    publication is converted into the frozen vector; every failure propagates
    and fails the task with no report row.
    """
    selector = params.opendata_stock_daily_snapshot
    if selector is None:
        return
    parameters = task.parameters_json
    if not isinstance(parameters, dict):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if parameters.get("opendata_stock_daily_evidence") is not None:
        return
    reader = host.stock_daily_snapshot_reader
    if reader is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_reader_unavailable")
    async with host.evidence_session_factory() as evidence_session:
        try:
            publication = await reader.read_authorized(
                selector=selector,
                user_id=task.user_id,
                session=evidence_session,
            )
        except (
            OpendataStockDailySnapshotError,
            StockDailySnapshotAuthorizationError,
        ) as exc:
            raise StockDailyReportEvidenceError(exc.code) from exc
    vector = build_stock_daily_report_evidence_vector(
        selector=selector,
        publication=publication,
    )
    parameters["opendata_stock_daily_evidence"] = vector.to_json()
    flag_modified(task, "parameters_json")


def build_stock_daily_report_evidence_vector(
    *,
    selector: StockAnalysisStockDailySnapshotSelection,
    publication: StockDailyAuthorizedPublication,
) -> StockDailyReportEvidenceVector:
    """Build and cross-check the vector for one authorized publication read.

    The returned vector names the same dataset/source/instrument/publication/
    sequence/content/contract facts the selector declares. Any difference is
    rejected with the existing expectation failure codes rather than repaired.

    Args:
        selector: The task's exact pinned selection.
        publication: The reader's authorized snapshot and authorization receipt.

    Raises:
        StockDailyReportEvidenceError: If any required publication fact is
            missing, malformed, or does not match the selector.
    """
    if not isinstance(selector, StockAnalysisStockDailySnapshotSelection):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if not isinstance(publication, StockDailyAuthorizedPublication):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    result = publication.result
    receipt = publication.receipt
    if not isinstance(result, OpendataPublishedSnapshotResult) or not isinstance(
        receipt, StockAnalysisSnapshotAuthorizationReceipt
    ):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")

    snapshot = result.snapshot
    if not isinstance(snapshot, Mapping):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if snapshot.get("dataset_id") != DATASET_ID:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    source = snapshot.get("source")
    if not isinstance(source, Mapping) or source.get("source_id") != SOURCE_ID:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")

    instrument_id, market = _publication_instrument(snapshot.get("stock_selection"))
    publication_id = snapshot.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_missing")
    publication_sequence = snapshot.get("sequence")
    if type(publication_sequence) is not int or publication_sequence < 1:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")

    evidence = StockDailyReportEvidence(
        dataset_id=DATASET_ID,
        source_id=SOURCE_ID,
        instrument_id=instrument_id,
        market=market,
        publication_id=publication_id,
        publication_sequence=publication_sequence,
        content_sha256=_require_sha256(snapshot.get("content_sha256")),
        contract_sha256=_require_sha256(snapshot.get("contract_sha256")),
        captured_at=_parse_utc(snapshot.get("created_at")),
        observed_at=_publication_observed_at(result.records),
        principal_user_id=receipt.principal_user_id,
        entitlement_revision=receipt.entitlement_revision,
        user_grant_id=receipt.user_grant_id,
        user_grant_revision=receipt.user_grant_revision,
        user_grant_valid_from=receipt.user_grant_valid_from,
        user_grant_expires_at=receipt.user_grant_expires_at,
        source_grant_id=receipt.source_grant_id,
        source_grant_revision=receipt.source_grant_revision,
        source_grant_valid_from=receipt.source_grant_valid_from,
        source_grant_expires_at=receipt.source_grant_expires_at,
        authorized_at=receipt.authorized_at,
        expires_at=receipt.expires_at,
        purpose=RESEARCH_PURPOSE,
        authorization_receipt=receipt,
    )
    vector = StockDailyReportEvidenceVector(entries=(evidence,))
    vector.ensure_matches(
        (
            stock_daily_report_evidence_expectation(
                instrument_id=selector.instrument_id,
                publication_id=selector.publication_id,
                publication_sequence=selector.publication_sequence,
                content_sha256=selector.content_sha256,
                contract_sha256=selector.contract_sha256,
            ),
        )
    )
    return vector


def _publication_instrument(stock_selection: object) -> tuple[str, str]:
    """Return the exact policy instrument named by the snapshot selection."""
    if not isinstance(stock_selection, Mapping):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    request_market = stock_selection.get("market")
    symbol = stock_selection.get("symbol")
    market = (
        _POLICY_MARKET_BY_REQUEST_MARKET.get(request_market)
        if isinstance(request_market, str)
        else None
    )
    if market is None or not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return f"{symbol}.{market}", market


def _publication_observed_at(records: object) -> datetime:
    """Return the single source observation time recorded on every row.

    The stock-daily publication has no snapshot-level observation time. Rows
    carry the platform's source observation timestamp; using any other field
    (such as ``as_of`` or ``created_at``) would relabel a different semantic.
    """
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence) or not records:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    observed_at: datetime | None = None
    for record in records:
        if not isinstance(record, Mapping):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        row_observed_at = _parse_utc(record.get("observed_at"))
        if observed_at is None:
            observed_at = row_observed_at
        elif row_observed_at != observed_at:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if observed_at is None:  # pragma: no cover - guarded by the non-empty check
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return observed_at


def _require_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _parse_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (OverflowError, TypeError, ValueError) as exc:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid") from exc
    else:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return parsed.astimezone(_UTC)


__all__ = [
    "StockDailyAuthorizedPublication",
    "StockDailyReportEvidenceReader",
    "build_stock_daily_report_evidence_vector",
    "produce_report_evidence",
]
