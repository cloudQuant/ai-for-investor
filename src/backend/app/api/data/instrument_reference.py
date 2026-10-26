"""Compose the optional published reference catalog at the HTTP boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
)
from app.services.market_data.opendata_credentials import (
    OpendataCredentials,
    OpendataCredentialsError,
)
from app.services.market_data.opendata_instrument_reference import (
    InstrumentReferenceClient,
    InstrumentReferenceConfig,
    InstrumentReferenceError,
)

_REFERENCE_STATUSES = {
    "OPENDATA_REFERENCE_UNAVAILABLE": 503,
    "OPENDATA_REFERENCE_PROTOCOL_INVALID": 503,
    "OPENDATA_REFERENCE_LIMIT_EXCEEDED": 503,
    "OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED": 422,
    "OPENDATA_REFERENCE_CONFIG_INVALID": 503,
    "OPENDATA_REFERENCE_RATE_LIMITED": 429,
}
_AUTHORIZATION_CODES = frozenset(
    {
        "MARKET_DATA_ACCESS_CHANGED_DURING_FETCH",
        "MARKET_DATA_ACCESS_REQUIRED",
        "MARKET_DATA_PRINCIPAL_INVALID",
        "MARKET_DATA_PRINCIPAL_REVOKED",
        "MARKET_DATA_READ_ENTITLEMENT_DENIED",
    }
)
InstrumentReferenceSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class InstrumentReferenceReader(Protocol):
    """The explicit async reader accepted by the route composition."""

    async def list_options(
        self, *, search: str = "", limit: int = 80, effective_on: date | None = None
    ) -> dict[str, JsonValue]:
        """Return a fully validated reference selection."""
        ...


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCatalog:
    """A request-local switch and deferred, server-owned client factory."""

    enabled: bool
    client_factory: Callable[[], InstrumentReferenceReader] | None = field(default=None, repr=False)


def build_instrument_reference_catalog(
    settings: object, *, environment: Mapping[str, str] | None = None
) -> InstrumentReferenceCatalog:
    """Defer credential resolution and client construction until after authorization."""
    if getattr(settings, "MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED", False) is not True:
        return InstrumentReferenceCatalog(enabled=False)

    def create_client() -> InstrumentReferenceReader:
        try:
            credentials = OpendataCredentials.from_environment(environment=environment)
        except OpendataCredentialsError:
            raise InstrumentReferenceError("OPENDATA_REFERENCE_CONFIG_INVALID") from None
        if credentials is None:
            raise InstrumentReferenceError("OPENDATA_REFERENCE_CONFIG_INVALID")
        return InstrumentReferenceClient(
            InstrumentReferenceConfig(
                base_url=credentials.base_url,
                api_key=credentials.api_key,
                dataset_id=getattr(settings, "MARKET_DATA_OPENDATA_INSTRUMENT_DATASET_ID", ""),
                source_id=getattr(settings, "MARKET_DATA_OPENDATA_INSTRUMENT_SOURCE_ID", ""),
                contract_sha256=getattr(
                    settings, "MARKET_DATA_OPENDATA_INSTRUMENT_CONTRACT_SHA256", ""
                ),
            )
        )

    return InstrumentReferenceCatalog(enabled=True, client_factory=create_client)


def get_instrument_reference_catalog() -> InstrumentReferenceCatalog:
    """Resolve the optional switch from server settings without touching a source."""
    return build_instrument_reference_catalog(get_settings())


def get_instrument_reference_session_factory() -> InstrumentReferenceSessionFactory:
    """Defer opening the control session until the enabled stock branch needs it."""
    return asynccontextmanager(get_db)


def _failure(status_code: int, code: str) -> HTTPException:
    """Build the bounded error envelope consumed by the catalog UI."""
    return HTTPException(status_code=status_code, detail={"code": code, "catalog_mode": "opendata"})


def _effective_date(value: str | None) -> date | None:
    """Require an explicit canonical business date without substituting today."""
    if value is None:
        return None
    if len(value) != 10:
        raise _failure(422, "OPENDATA_REFERENCE_REQUEST_INVALID")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _failure(422, "OPENDATA_REFERENCE_REQUEST_INVALID") from None
    if parsed.isoformat() != value:
        raise _failure(422, "OPENDATA_REFERENCE_REQUEST_INVALID")
    return parsed


async def read_instrument_reference_options(
    *,
    catalog: InstrumentReferenceCatalog,
    db: AsyncSession,
    authorizer: MarketDataAccessAuthorizer,
    current_user: object,
    search: str,
    limit: int,
    effective_on: str | None,
) -> dict[str, JsonValue]:
    """Read outside a DB transaction and refresh entitlement before returning data."""
    try:
        try:
            principal = await authorizer.principal_for_user(current_user)
            authorizer.require_read_data(principal=principal)
            # A repeatable-read snapshot must not survive the external fetch.
            await db.rollback()
            if len(search) > 128 or not 1 <= limit <= 80:
                raise _failure(422, "OPENDATA_REFERENCE_REQUEST_INVALID")
            effective_date = _effective_date(effective_on)
            if catalog.client_factory is None:
                raise InstrumentReferenceError("OPENDATA_REFERENCE_CONFIG_INVALID")
            result = await catalog.client_factory().list_options(
                search=search, limit=limit, effective_on=effective_date
            )
            refreshed = await authorizer.revalidate_principal(principal=principal)
            authorizer.require_read_data(principal=refreshed)
            return result
        finally:
            # Both successful reads and denials release the request's control DB read.
            await db.rollback()
    except MarketDataAuthorizationError as exc:
        code = exc.code if exc.code in _AUTHORIZATION_CODES else "MARKET_DATA_ACCESS_REQUIRED"
        raise _failure(403, code) from None
    except InstrumentReferenceError as exc:
        code = exc.code if exc.code in _REFERENCE_STATUSES else "OPENDATA_REFERENCE_UNAVAILABLE"
        raise _failure(_REFERENCE_STATUSES[code], code) from None
    except SQLAlchemyError:
        raise _failure(503, "OPENDATA_REFERENCE_UNAVAILABLE") from None
