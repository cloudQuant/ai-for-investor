"""Canonical research-vector and publication contract primitives.

This module owns the frozen publication receipt, the deterministic CSV vector
materialization, the content/contract digests, and the strict fail-closed
validators that a market-data research binding seals into its manifest.  It was
extracted verbatim from ``research_binding``; that module re-imports these
names so existing import paths remain stable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from app.models.market_data_platform import MdResearchDataBinding
from app.schemas.market_data_platform import ResolvedMarketDataQuery
from app.services.market_data.publication import (
    PUBLICATION_SOURCE_SNAPSHOT,
    MarketDataVisibilityAnchor,
)
from app.services.market_data.query_service import MarketDataQueryExecution

UTC = timezone.utc


class MarketDataResearchBindingError(ValueError):
    """Stable fail-closed error raised by the research binding boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_PUBLICATION_BINDING_SCHEMA_VERSION = "market-data-research-publication-binding-v1"
_QUERY_CONTRACT_VERSION = "market-data-query-v1"


_CSV_COLUMNS = ("datetime", "open", "high", "low", "close", "volume", "openinterest")
_ASSET_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


# A publication identifier is either one OpenData 32-hex publication id or one
# local ``md_publications.id`` canonical UUID.  Both are lower-case content
# identity keys; anything else (a name, a path, a timestamp) is rejected rather
# than resolved, so a binding can never pin a loosely described snapshot.
_PUBLICATION_ID_PATTERN = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


_PUBLICATION_SECTION_KEYS = frozenset({"schema_version", "entity_type", "datasets"})
_PUBLICATION_RECEIPT_KEYS = frozenset(
    {
        "publication_id",
        "source_snapshot_id",
        "entity_sha256",
        "visible_at",
        "visibility_sequence",
    }
)
_PUBLICATION_FILTER_KEYS = frozenset({"asset_type", "symbol", "timeframe", "timeframe_n"})
_CONTRACT_BASIS_FIELDS = (
    "contract_version",
    "canonical_id",
    "dataset_code",
    "data_kind",
    "family_id",
    "family_contract_version",
    "frequency",
    "required_fields",
    "adjustment",
    "price_basis",
    "currency",
    "unit",
    "source_policy_id",
    "instrument_metadata_version",
    "consistency",
    "purpose",
    "mode",
)
_PUBLICATION_DATASET_KEYS = frozenset(
    (
        *_CONTRACT_BASIS_FIELDS,
        "window_start",
        "window_end",
        "knowledge_cutoff",
        "filters",
        "contract_sha256",
        "content_sha256",
        "publications",
    )
)
_CONTRACT_TEXT_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "canonical_id": 512,
        "dataset_code": 255,
        "data_kind": 64,
        "family_id": 128,
        "family_contract_version": 64,
        "frequency": 32,
        "source_policy_id": 128,
        "instrument_metadata_version": 128,
        "consistency": 32,
        "purpose": 32,
        "mode": 32,
    }
)
_CONTRACT_OPTIONAL_TEXT_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "adjustment": 128,
        "price_basis": 128,
        "currency": 32,
        "unit": 128,
    }
)
_PUBLICATION_SEMANTIC_BASIS_FIELDS = (
    "canonical_id",
    "dataset_code",
    "data_kind",
    "family_id",
    "family_contract_version",
    "frequency",
    "source_policy_id",
    "instrument_metadata_version",
)


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_OBSERVATION_INVALID")
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_runtime_timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return _aware_utc(value, field_name)
    if not isinstance(value, str) or not value.strip():
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_RUNTIME_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketDataResearchBindingError(
            "MARKET_DATA_BINDING_RUNTIME_TIMESTAMP_INVALID"
        ) from exc
    return _aware_utc(parsed, field_name)


def _required_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return normalized


def _required_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return value


def _required_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return value


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_timeframe(value: object) -> str:
    if not isinstance(value, str):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_TIMEFRAME_UNSUPPORTED")
    normalized = value.strip().lower()
    if normalized not in {"1d", "1w", "1mo"}:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_TIMEFRAME_UNSUPPORTED")
    return normalized


def _normalized_asset_type(value: object) -> str:
    if not isinstance(value, str):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    normalized = value.strip().lower()
    if _ASSET_TYPE_PATTERN.fullmatch(normalized) is None:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return normalized


def _validated_query_semantics(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    expected_keys = {
        "asset_type",
        "symbol",
        "timeframe",
        "timeframe_n",
        "full_window_start",
        "full_window_end",
        "canonical_id",
        "dataset_code",
        "family_id",
        "family_contract_version",
        "data_kind",
        "frequency",
        "source_policy_id",
        "instrument_metadata_version",
        "query_fingerprint",
    }
    if set(value) != expected_keys:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    normalized = {
        "asset_type": _normalized_asset_type(value["asset_type"]),
        "symbol": _required_text(value["symbol"], "symbol", 50),
        "timeframe": _normalized_timeframe(value["timeframe"]),
        "timeframe_n": _required_positive_int(value["timeframe_n"], "timeframe_n"),
        "full_window_start": _iso_utc(
            _parse_runtime_timestamp(value["full_window_start"], "full_window_start")
        ),
        "full_window_end": _iso_utc(
            _parse_runtime_timestamp(value["full_window_end"], "full_window_end")
        ),
        "canonical_id": _required_text(value["canonical_id"], "canonical_id", 512),
        "dataset_code": _required_text(value["dataset_code"], "dataset_code", 255),
        "family_id": _required_text(value["family_id"], "family_id", 128),
        "family_contract_version": _required_text(
            value["family_contract_version"],
            "family_contract_version",
            64,
        ),
        "data_kind": _required_text(value["data_kind"], "data_kind", 64),
        "frequency": _required_text(value["frequency"], "frequency", 32),
        "source_policy_id": _required_text(value["source_policy_id"], "source_policy_id", 128),
        "instrument_metadata_version": _required_text(
            value["instrument_metadata_version"],
            "instrument_metadata_version",
            128,
        ),
        "query_fingerprint": _required_sha256(
            value["query_fingerprint"],
            "query_fingerprint",
        ),
    }
    if normalized["timeframe_n"] != 1:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    start = _parse_runtime_timestamp(normalized["full_window_start"], "full_window_start")
    end = _parse_runtime_timestamp(normalized["full_window_end"], "full_window_end")
    if start >= end or normalized["data_kind"] != "bars":
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    return normalized


def _csv_required_number(value: object, field_name: str) -> str:
    if value is None:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_OHLC_REQUIRED")
    try:
        return _format_decimal(value, field_name=field_name)
    except MarketDataResearchBindingError as exc:
        if exc.code == "MARKET_DATA_BINDING_NUMERIC_INVALID":
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_OHLC_REQUIRED") from exc
        raise


def _csv_optional_number(value: object, field_name: str) -> str:
    if value is None:
        return ""
    return _format_decimal(value, field_name=field_name)


def _format_decimal(value: object, *, field_name: str) -> str:
    if isinstance(value, bool):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_NUMERIC_INVALID")
    try:
        if isinstance(value, Decimal):
            decimal_value = value
        elif isinstance(value, (int, float, str)):
            if isinstance(value, float) and not math.isfinite(value):
                raise InvalidOperation
            decimal_value = Decimal(str(value).strip())
        else:
            raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_NUMERIC_INVALID") from exc
    if not decimal_value.is_finite():
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_NUMERIC_INVALID")
    rendered = format(decimal_value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _materialize_csv(execution: MarketDataQueryExecution) -> tuple[bytes, list[dict[str, object]]]:
    rows = sorted(
        execution.observations,
        key=lambda item: (
            _aware_utc(item.event_at, "event_at"),
            item.visibility_sequence,
            item.revision_number,
            item.revision_id,
        ),
    )
    if not rows:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_NO_OBSERVATIONS")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    evidence: list[dict[str, object]] = []
    previous_event_at: datetime | None = None
    for item in rows:
        event_at = _aware_utc(item.event_at, "event_at")
        if previous_event_at == event_at:
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_DUPLICATE_EVENT")
        previous_event_at = event_at
        fields = item.fields
        if not isinstance(fields, Mapping):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_OBSERVATION_INVALID")
        open_value = _csv_required_number(fields.get("open"), "open")
        high_value = _csv_required_number(fields.get("high"), "high")
        low_value = _csv_required_number(fields.get("low"), "low")
        close_value = _csv_required_number(fields.get("close"), "close")
        volume_value = _csv_optional_number(fields.get("volume"), "volume")
        open_interest = fields.get("openinterest", fields.get("open_interest"))
        open_interest_value = _csv_optional_number(open_interest, "openinterest")
        writer.writerow(
            (
                _iso_utc(event_at),
                open_value,
                high_value,
                low_value,
                close_value,
                volume_value,
                open_interest_value,
            )
        )
        evidence.append(
            {
                "revision_id": _required_text(item.revision_id, "revision_id", 36),
                "source_snapshot_id": _required_text(
                    item.source_snapshot_id,
                    "source_snapshot_id",
                    36,
                ),
                "event_at": _iso_utc(event_at),
                "available_at": _iso_utc(_aware_utc(item.available_at, "available_at")),
                "visibility_sequence": _required_nonnegative_int(
                    item.visibility_sequence,
                    "visibility_sequence",
                ),
                "revision_number": _required_positive_int(item.revision_number, "revision_number"),
            }
        )
    return output.getvalue().encode("utf-8"), evidence


def _sealed_source_snapshot_ids(evidence: object) -> tuple[str, ...]:
    """Return every immutable source snapshot that contributed sealed bytes."""
    if not isinstance(evidence, list):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    source_snapshot_ids: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
        source_snapshot_ids.add(
            _required_text(item.get("source_snapshot_id"), "source_snapshot_id", 36)
        )
    if not source_snapshot_ids:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_NO_OBSERVATIONS")
    return tuple(sorted(source_snapshot_ids))


@dataclass(frozen=True, slots=True)
class MarketDataPublicationReceipt:
    """One sealed ``md_publications`` receipt for a contributing source snapshot.

    The receipt carries only facts already sealed by the publication protocol:
    the publication identifier, its globally monotonic visibility sequence, the
    post-commit visibility instant, and the entity digest.  It is deliberately
    free of provider names, filesystem paths, or timestamps inferred from an ORM
    ``created_at`` so a research binding can pin it and re-verify it later.
    """

    publication_id: str
    source_snapshot_id: str
    entity_sha256: str
    visible_at: datetime
    visibility_sequence: int

    def to_json(self) -> dict[str, object]:
        """Return the receipt in the exact canonical form stored in a manifest."""
        return {
            "publication_id": self.publication_id,
            "source_snapshot_id": self.source_snapshot_id,
            "entity_sha256": self.entity_sha256,
            "visible_at": _iso_utc(_aware_utc(self.visible_at, "visible_at")),
            "visibility_sequence": _required_positive_int(
                self.visibility_sequence,
                "visibility_sequence",
            ),
        }


def market_data_binding_content_sha256(
    *,
    csv_content: bytes,
    observation_evidence: Sequence[Mapping[str, object]],
) -> str:
    """Return the canonical record-set digest of one sealed research vector.

    The digest covers the artifact's actual business values in artifact order and
    every row's sealed provenance.  It is deliberately distinct from the
    artifact's byte hash: a later run recomputes it from the artifact plus its
    manifest and can therefore detect a changed vector, a dropped row, or a
    revision that no longer belongs to the same publication set.
    """
    rows = _artifact_csv_rows(csv_content)
    if len(rows) != len(observation_evidence):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_CONTENT_ROWS_MISMATCH")
    provenance = [_validated_observation_provenance(item) for item in observation_evidence]
    return _canonical_sha256(
        {
            "columns": list(_CSV_COLUMNS),
            "rows": rows,
            "provenance": provenance,
        }
    )


def _artifact_csv_rows(csv_content: bytes) -> list[list[str]]:
    """Return the artifact's business rows, rejecting any header or shape drift."""
    try:
        decoded = csv_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_CONTENT_INVALID") from exc
    parsed = list(csv.reader(io.StringIO(decoded)))
    if not parsed or parsed[0] != list(_CSV_COLUMNS):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_CONTENT_COLUMNS_INVALID")
    rows = parsed[1:]
    if any(len(row) != len(_CSV_COLUMNS) for row in rows):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_CONTENT_ROWS_INVALID")
    return [list(row) for row in rows]


def _validated_observation_provenance(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "revision_id",
        "source_snapshot_id",
        "event_at",
        "available_at",
        "visibility_sequence",
        "revision_number",
    }:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_CONTENT_PROVENANCE_INVALID")
    return {
        "revision_id": _required_text(value["revision_id"], "revision_id", 36),
        "source_snapshot_id": _required_text(value["source_snapshot_id"], "source_snapshot_id", 36),
        "event_at": _iso_utc(_parse_runtime_timestamp(value["event_at"], "event_at")),
        "available_at": _iso_utc(_parse_runtime_timestamp(value["available_at"], "available_at")),
        "visibility_sequence": _required_nonnegative_int(
            value["visibility_sequence"],
            "visibility_sequence",
        ),
        "revision_number": _required_positive_int(value["revision_number"], "revision_number"),
    }


def _publication_contract_basis(
    *,
    query: ResolvedMarketDataQuery,
    query_semantics: Mapping[str, object],
) -> dict[str, object]:
    """Freeze the contract-shape fields that determine the vector's semantics.

    The identity/contract axes are copied from the already-validated query
    semantics so a pinned contract can never disagree with the contract the
    binding actually executed; the remaining shape fields are read from the exact
    resolved query.  ``None`` is preserved as ``None`` for the four optional
    bases rather than replaced by a guessed default.
    """
    basis: dict[str, object] = {"contract_version": _QUERY_CONTRACT_VERSION}
    for field_name in _PUBLICATION_SEMANTIC_BASIS_FIELDS:
        basis[field_name] = query_semantics[field_name]
    basis.update(
        {
            "required_fields": sorted({str(name) for name in query.required_fields}),
            "adjustment": query.adjustment,
            "price_basis": query.price_basis,
            "currency": query.currency,
            "unit": query.unit,
            "consistency": str(query.consistency),
            "purpose": str(query.purpose),
            "mode": str(query.mode),
        }
    )
    return basis


def market_data_binding_contract_sha256(basis: Mapping[str, object]) -> str:
    """Return the contract hash for one pinned publication contract basis.

    A later run recomputes this digest from the pinned basis to prove that the
    contract it is about to read is the contract the binding sealed.  A basis
    missing any axis is refused instead of hashed with an implicit default.
    """
    if any(field not in basis for field in _CONTRACT_BASIS_FIELDS):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_INVALID")
    return _canonical_sha256({field: basis[field] for field in _CONTRACT_BASIS_FIELDS})


def _publication_filters(query_semantics: Mapping[str, object]) -> dict[str, object]:
    """Return the selection filters pinned beside the contract basis."""
    return {
        "asset_type": query_semantics["asset_type"],
        "symbol": query_semantics["symbol"],
        "timeframe": query_semantics["timeframe"],
        "timeframe_n": query_semantics["timeframe_n"],
    }


def _build_publication_binding_section(
    *,
    query: ResolvedMarketDataQuery,
    query_semantics: Mapping[str, object],
    csv_content: bytes,
    observation_evidence: Sequence[Mapping[str, object]],
    knowledge_cutoff: datetime,
    receipts: Sequence[MarketDataPublicationReceipt],
) -> dict[str, object]:
    """Assemble the per-dataset publication pin section stored inside a binding."""
    if not receipts:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_MISSING")
    ordered = sorted(
        receipts,
        key=lambda item: (
            _required_positive_int(item.visibility_sequence, "visibility_sequence"),
            item.publication_id,
        ),
    )
    basis = _publication_contract_basis(query=query, query_semantics=query_semantics)
    dataset: dict[str, object] = {
        **basis,
        "window_start": _iso_utc(query.start),
        "window_end": _iso_utc(query.end),
        "knowledge_cutoff": _iso_utc(knowledge_cutoff),
        "filters": _publication_filters(query_semantics),
        "contract_sha256": market_data_binding_contract_sha256(basis),
        "content_sha256": market_data_binding_content_sha256(
            csv_content=csv_content,
            observation_evidence=observation_evidence,
        ),
        "publications": [receipt.to_json() for receipt in ordered],
    }
    return {
        "schema_version": _PUBLICATION_BINDING_SCHEMA_VERSION,
        "entity_type": PUBLICATION_SOURCE_SNAPSHOT,
        "datasets": [dataset],
    }


def _validated_publication_binding(material: Mapping[str, object]) -> dict[str, Any]:
    """Rebuild and verify one material's pinned publication section.

    ``Any`` in the value position is deliberate, not a shortcut: this function refuses
    anything whose axes do not match the sealed material, and in particular guarantees
    ``datasets`` is a one-element list, so callers may iterate it without re-testing a
    condition that cannot be false here.

    Every axis is checked against the rest of the sealed material: the dataset
    contract basis must agree with the query semantics, the window must agree
    with the query, the pinned content hash must be recomputable only from the
    sealed vector, and each publication receipt must fall inside the material's
    frozen visibility anchor.  A missing reference, a malformed identifier, or a
    receipt outside the anchor is refused; nothing is inferred.
    """
    section = material.get("publications")
    if not isinstance(section, Mapping) or set(section) != _PUBLICATION_SECTION_KEYS:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    if (
        section.get("schema_version") != _PUBLICATION_BINDING_SCHEMA_VERSION
        or section.get("entity_type") != PUBLICATION_SOURCE_SNAPSHOT
    ):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    datasets = section.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != 1:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_DATASET_INVALID")
    semantics = _validated_query_semantics(material.get("query_semantics"))
    anchor = _validated_pit_anchor(material.get("pit"))
    observations = material.get("observations")
    if not isinstance(observations, list) or not observations:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    sealed_snapshot_ids = {
        _required_text(item["source_snapshot_id"], "source_snapshot_id", 36)
        for item in (_validated_observation_provenance(item) for item in observations)
    }
    normalized_datasets = [
        _validated_publication_dataset(
            item,
            query_semantics=semantics,
            anchor=anchor,
            sealed_snapshot_ids=sealed_snapshot_ids,
        )
        for item in datasets
    ]
    return {
        "schema_version": _PUBLICATION_BINDING_SCHEMA_VERSION,
        "entity_type": PUBLICATION_SOURCE_SNAPSHOT,
        "datasets": normalized_datasets,
    }


def _validated_pit_anchor(value: object) -> MarketDataVisibilityAnchor:
    """Rebuild the binding's frozen visibility anchor from its sealed PIT axis."""
    if not isinstance(value, Mapping):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    try:
        visible_at = _parse_runtime_timestamp(value["visibility_at"], "visibility_at")
        maximum = _required_nonnegative_int(value["visibility_sequence"], "visibility_sequence")
    except (KeyError, MarketDataResearchBindingError, ValueError) as exc:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID") from exc
    return MarketDataVisibilityAnchor(visible_at=visible_at, max_visibility_sequence=maximum)


def _validated_publication_dataset(
    value: object,
    *,
    query_semantics: Mapping[str, object],
    anchor: MarketDataVisibilityAnchor,
    sealed_snapshot_ids: set[str],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PUBLICATION_DATASET_KEYS:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_DATASET_INVALID")
    basis: dict[str, object] = {"contract_version": _QUERY_CONTRACT_VERSION}
    for field_name in _CONTRACT_BASIS_FIELDS:
        if field_name == "contract_version":
            continue
        if field_name == "required_fields":
            basis[field_name] = _validated_required_fields(value[field_name])
        elif field_name in _CONTRACT_OPTIONAL_TEXT_LIMITS:
            basis[field_name] = _validated_optional_contract_text(
                value[field_name],
                field_name=field_name,
                maximum=_CONTRACT_OPTIONAL_TEXT_LIMITS[field_name],
            )
        else:
            basis[field_name] = _required_text(
                value[field_name],
                field_name,
                _CONTRACT_TEXT_LIMITS[field_name],
            )
    if basis["contract_version"] != value["contract_version"]:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_INVALID")
    if any(
        basis[field_name] != query_semantics[field_name]
        for field_name in _PUBLICATION_SEMANTIC_BASIS_FIELDS
    ):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_MISMATCH")
    if (
        basis["data_kind"] != "bars"
        or basis["mode"] != "local_only"
        or basis["purpose"] != "backtest"
        or basis["consistency"] != "strict"
    ):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_INVALID")
    window_start = _iso_utc(_parse_runtime_timestamp(value["window_start"], "window_start"))
    window_end = _iso_utc(_parse_runtime_timestamp(value["window_end"], "window_end"))
    if (
        window_start >= window_end
        or window_start != query_semantics["full_window_start"]
        or window_end != query_semantics["full_window_end"]
    ):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_WINDOW_INVALID")
    knowledge_cutoff = _iso_utc(_parse_runtime_timestamp(value["knowledge_cutoff"], "cutoff"))
    filters = _validated_publication_filters(value["filters"], query_semantics)
    if market_data_binding_contract_sha256(basis) != _required_sha256(
        value["contract_sha256"],
        "contract_sha256",
    ):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_MISMATCH")
    content_sha256 = _required_sha256(value["content_sha256"], "content_sha256")
    receipts = _validated_publication_receipts(
        value["publications"],
        anchor=anchor,
        sealed_snapshot_ids=sealed_snapshot_ids,
    )
    normalized = {
        **basis,
        "window_start": window_start,
        "window_end": window_end,
        "knowledge_cutoff": knowledge_cutoff,
        "filters": filters,
        "contract_sha256": market_data_binding_contract_sha256(basis),
        "content_sha256": content_sha256,
        "publications": receipts,
    }
    if normalized != dict(value):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    return normalized


def _validated_required_fields(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_INVALID")
    fields = [_required_text(item, "required_fields", 128) for item in value]
    if len(set(fields)) != len(fields) or fields != sorted(fields):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_CONTRACT_INVALID")
    return fields


def _validated_optional_contract_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name, maximum)


def _validated_publication_filters(
    value: object,
    query_semantics: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PUBLICATION_FILTER_KEYS:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_FILTERS_INVALID")
    normalized = {
        "asset_type": _normalized_asset_type(value["asset_type"]),
        "symbol": _required_text(value["symbol"], "symbol", 50),
        "timeframe": _normalized_timeframe(value["timeframe"]),
        "timeframe_n": _required_positive_int(value["timeframe_n"], "timeframe_n"),
    }
    if any(normalized[field_name] != query_semantics[field_name] for field_name in normalized):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_FILTERS_MISMATCH")
    return normalized


def _validated_publication_receipts(
    value: object,
    *,
    anchor: MarketDataVisibilityAnchor,
    sealed_snapshot_ids: set[str],
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_MISSING")
    receipts: list[dict[str, object]] = []
    publication_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    previous_order: tuple[int, str] | None = None
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _PUBLICATION_RECEIPT_KEYS:
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
        publication_id = item.get("publication_id")
        if (
            not isinstance(publication_id, str)
            or _PUBLICATION_ID_PATTERN.fullmatch(publication_id) is None
        ):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_ID_INVALID")
        source_snapshot_id = _required_text(
            item["source_snapshot_id"],
            "source_snapshot_id",
            36,
        )
        sequence = _required_positive_int(item["visibility_sequence"], "visibility_sequence")
        visible_at = _parse_runtime_timestamp(item["visible_at"], "visible_at")
        if publication_id in publication_ids or source_snapshot_id in snapshot_ids:
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_DUPLICATE")
        order = (sequence, publication_id)
        if previous_order is not None and order <= previous_order:
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_ORDER_INVALID")
        previous_order = order
        if not anchor.permits(visible_at=visible_at, visibility_sequence=sequence):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_OUT_OF_ANCHOR")
        publication_ids.add(publication_id)
        snapshot_ids.add(source_snapshot_id)
        receipts.append(
            {
                "publication_id": publication_id,
                "source_snapshot_id": source_snapshot_id,
                "entity_sha256": _required_sha256(item["entity_sha256"], "entity_sha256"),
                "visible_at": _iso_utc(visible_at),
                "visibility_sequence": sequence,
            }
        )
    if snapshot_ids != sealed_snapshot_ids:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INCOMPLETE")
    return receipts


def _manifest_publication_pins(manifest: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    material = manifest.get("material")
    if not isinstance(material, Mapping):
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_MANIFEST_INVALID")
    section = _validated_publication_binding(material)
    pins: list[Mapping[str, object]] = []
    for raw_dataset in section["datasets"]:
        if not isinstance(raw_dataset, dict):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
        dataset: dict[str, object] = dict(raw_dataset)
        raw_publications = dataset["publications"]
        if not isinstance(raw_publications, list):
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
        receipts: list[Mapping[str, object]] = []
        for raw_receipt in raw_publications:
            if not isinstance(raw_receipt, dict):
                raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
            receipts.append(MappingProxyType(dict(raw_receipt)))
        dataset["publications"] = tuple(receipts)
        pins.append(MappingProxyType(dataset))
    return tuple(pins)


def market_data_binding_publication_pins(
    manifest: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Return the validated per-dataset publication pins of one sealed binding.

    Consumers (a backtest runner or an export manifest) use this to record and
    re-verify the exact publications a binding was built from.  Anything that
    does not validate is refused with a stable error code instead of returning a
    partial or guessed pin set.
    """
    return _manifest_publication_pins(manifest)


def _validate_publication_binding_matches_binding(
    *,
    binding: MdResearchDataBinding,
    material: Mapping[str, object],
) -> None:
    """Require the pinned publications to name this binding's dataset and anchor.

    The JSON section already cross-checks its own axes; this second pass binds
    those axes to the relational audit columns so a direct database update of the
    dataset identity or of the visibility sequence cannot survive manifest
    validation.  A binding without a complete publication reference is refused.
    """
    section = _validated_publication_binding(material)
    datasets = section["datasets"]
    if not isinstance(datasets, list) or len(datasets) != 1:
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_DATASET_INVALID")
    dataset = datasets[0]
    if not isinstance(dataset, dict):  # pragma: no cover - validated above
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    expected_dataset_columns = {
        "canonical_id": binding.canonical_id,
        "dataset_code": binding.dataset_code,
        "family_id": binding.family_id,
        "family_contract_version": binding.family_contract_version,
        "data_kind": binding.data_kind,
        "frequency": binding.frequency,
        "source_policy_id": binding.source_policy_id,
        "instrument_metadata_version": binding.instrument_metadata_version,
    }
    for field_name, column_value in expected_dataset_columns.items():
        if dataset[field_name] != column_value:
            raise MarketDataResearchBindingError(
                "MARKET_DATA_BINDING_PUBLICATION_CONTRACT_MISMATCH"
            )
    publications = dataset["publications"]
    if not isinstance(publications, list):  # pragma: no cover - validated above
        raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
    for receipt in publications:
        if not isinstance(receipt, dict):  # pragma: no cover - validated above
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_INVALID")
        if receipt["visibility_sequence"] > binding.visibility_sequence:
            raise MarketDataResearchBindingError("MARKET_DATA_BINDING_PUBLICATION_OUT_OF_ANCHOR")
