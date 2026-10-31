"""Current-evidence authorization adapter for pinned stock-daily publications.

This default-off adapter joins the pure ``opendata_snapshot_authorization``
policy to authoritative persistence. It loads the current principal, the
greatest-revision user-read and source-research grants for one exact scope,
their issue/revocation audits, and the current ``AssetDataSourceRegistry`` row
for ``akshare.daily`` from a caller-provided async SQLAlchemy session. Caller
constructed evidence objects are never accepted as proof.

Stock-daily publications are time-series snapshots with no source-native
capture identifier. The exact publication ``content_sha256`` is therefore used
as the policy ``capture_id`` and stored in the grant scope. It is a platform
publication content digest, not a source capture or an issuer signature. The
authorized reader must receive the expected digest explicitly; it must not
infer the grant scope from a response after the fact.

Scope: dataset ``cn-equity-stock-daily``, source ``akshare.daily``, policy
markets ``SH``/``SZ`` (request markets ``CN-SSE``/``CN-SZSE``), instrument
``<six digits>.<SH|SZ>``, one publication ID, and the publication content hash.

What this module does not prove: issuer authentication, a production grant
registry or issuance API, real market data, deployment configuration, or
production acceptance. It performs no network I/O and has no file cache or
broad service-identity fallback. An unkeyed policy receipt still needs a
server-side MAC/signature at an untrusted persistence boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset_research import AssetDataSourceRegistry
from app.models.stock_analysis_snapshot_grant import (
    StockSnapshotGrantAudit,
    StockSnapshotSourceResearchGrant,
    StockSnapshotUserReadGrant,
)
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataPrincipal,
)
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RESEARCH_PURPOSE,
    CurrentPrincipalEvidence,
    CurrentSourceRegistryEvidence,
    SourceResearchGrantEvidence,
    StockAnalysisSnapshotAuthorizationError,
    StockAnalysisSnapshotAuthorizationReceipt,
    StockAnalysisSnapshotScope,
    UserReadDataGrantEvidence,
    authorize_stock_analysis_snapshot,
    revalidate_stock_analysis_snapshot,
)

DATASET_ID: Final = "cn-equity-stock-daily"
SOURCE_ID: Final = "akshare.daily"
_REQUEST_MARKET_BY_POLICY_MARKET: Final = {"SH": "CN-SSE", "SZ": "CN-SZSE"}
_SOURCE_REGISTRY_REVISION_VERSION: Final = "asset-source-registry-v1"
_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_CAPTURE_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class StockDailySnapshotAuthorizationError(ValueError):
    """Stable denial from the current-evidence stock-daily adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StockDailySnapshotAuthorizationAdapter:
    """Load current stock-daily grant evidence and evaluate the pure policy."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or _utc_now

    async def authorize(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        scope: StockAnalysisSnapshotScope,
    ) -> StockAnalysisSnapshotAuthorizationReceipt:
        """Authorize one exact pinned stock-daily read before provider I/O."""
        await self._begin_current_read(session)
        self._validate_scope(scope=scope, user_id=user_id)
        principal, market_principal = await self._load_principal(
            session=session,
            user_id=user_id,
        )
        user_grant = await self._load_user_grant(session=session, scope=scope)
        source_grant = await self._load_source_grant(session=session, scope=scope)
        source_registry = await self._load_source_registry(
            session=session,
            scope=scope,
            principal=principal,
            market_principal=market_principal,
        )
        try:
            return authorize_stock_analysis_snapshot(
                scope=scope,
                principal=principal,
                user_grant=user_grant,
                source_grant=source_grant,
                source_registry=source_registry,
                now=self._now(),
            )
        except StockAnalysisSnapshotAuthorizationError as exc:
            raise StockDailySnapshotAuthorizationError(exc.code) from exc

    async def revalidate(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        scope: StockAnalysisSnapshotScope,
        receipt: StockAnalysisSnapshotAuthorizationReceipt | None,
    ) -> StockAnalysisSnapshotAuthorizationReceipt:
        """Re-read every current row and recheck the creation receipt."""
        await self._begin_current_read(session)
        self._validate_scope(scope=scope, user_id=user_id)
        principal, market_principal = await self._load_principal(
            session=session,
            user_id=user_id,
        )
        user_grant = await self._load_user_grant(session=session, scope=scope)
        source_grant = await self._load_source_grant(session=session, scope=scope)
        source_registry = await self._load_source_registry(
            session=session,
            scope=scope,
            principal=principal,
            market_principal=market_principal,
        )
        try:
            return revalidate_stock_analysis_snapshot(
                scope=scope,
                receipt=receipt,
                principal=principal,
                user_grant=user_grant,
                source_grant=source_grant,
                source_registry=source_registry,
                now=self._now(),
            )
        except StockAnalysisSnapshotAuthorizationError as exc:
            raise StockDailySnapshotAuthorizationError(exc.code) from exc

    @staticmethod
    async def _begin_current_read(session: AsyncSession) -> None:
        """End an idle read transaction so the next query is a current read.

        The adapter never participates in a caller write. A session with
        pending changes is rejected rather than committing or discarding them.
        """
        if not isinstance(session, AsyncSession):
            raise StockDailySnapshotAuthorizationError("stock_daily_session_invalid")
        if not session.in_transaction():
            return
        if session.new or session.dirty or session.deleted:
            raise StockDailySnapshotAuthorizationError("stock_daily_session_has_pending_changes")
        await session.rollback()

    @staticmethod
    def _validate_scope(*, scope: StockAnalysisSnapshotScope, user_id: str) -> None:
        if not isinstance(scope, StockAnalysisSnapshotScope):
            raise StockDailySnapshotAuthorizationError("stock_daily_scope_invalid")
        if (
            not isinstance(user_id, str)
            or not 0 < len(user_id) <= 36
            or user_id.strip() != user_id
            or scope.user_id != user_id
            or scope.dataset_id != DATASET_ID
            or scope.source_id != SOURCE_ID
            or scope.market not in _REQUEST_MARKET_BY_POLICY_MARKET
            or not isinstance(scope.instrument_id, str)
            or _INSTRUMENT_ID.fullmatch(scope.instrument_id) is None
            or scope.instrument_id[-2:] != scope.market
            or not isinstance(scope.publication_id, str)
            or _PUBLICATION_ID.fullmatch(scope.publication_id) is None
            or not isinstance(scope.capture_id, str)
            or _CAPTURE_ID.fullmatch(scope.capture_id) is None
        ):
            raise StockDailySnapshotAuthorizationError("stock_daily_scope_invalid")

    async def _load_principal(
        self,
        *,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[CurrentPrincipalEvidence, MarketDataPrincipal]:
        """Read the current user/role entitlement and require ``data:read``."""
        authorizer = MarketDataAccessAuthorizer(session, clock=self._clock)
        try:
            market_principal = await authorizer.principal_for_user(SimpleNamespace(id=user_id))
            authorizer.require_read_data(principal=market_principal)
        except MarketDataAuthorizationError as exc:
            raise StockDailySnapshotAuthorizationError("stock_daily_principal_denied") from exc
        principal = CurrentPrincipalEvidence(
            user_id=market_principal.principal_id,
            is_active=True,
            permissions=frozenset(market_principal.permissions),
            entitlement_revision=market_principal.entitlement_revision,
        )
        return principal, market_principal

    async def _load_user_grant(
        self,
        *,
        session: AsyncSession,
        scope: StockAnalysisSnapshotScope,
    ) -> UserReadDataGrantEvidence:
        statement = (
            select(StockSnapshotUserReadGrant)
            .where(
                StockSnapshotUserReadGrant.user_id == scope.user_id,
                StockSnapshotUserReadGrant.dataset_id == scope.dataset_id,
                StockSnapshotUserReadGrant.instrument_id == scope.instrument_id,
                StockSnapshotUserReadGrant.market == scope.market,
                StockSnapshotUserReadGrant.publication_id == scope.publication_id,
                StockSnapshotUserReadGrant.capture_id == scope.capture_id,
                StockSnapshotUserReadGrant.purpose == RESEARCH_PURPOSE,
            )
            .order_by(StockSnapshotUserReadGrant.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        grant = (await session.execute(statement)).scalar_one_or_none()
        if grant is None:
            raise StockDailySnapshotAuthorizationError("stock_daily_user_grant_missing")
        revoked_at, revocation_revision = await self._load_audit_state(
            session=session,
            user_grant_id=grant.id,
            subject_user_id=grant.user_id,
            grant_revision=grant.revision,
        )
        return UserReadDataGrantEvidence(
            grant_id=grant.id,
            revision=grant.revision,
            revocation_revision=revocation_revision,
            permission=grant.permission,
            user_id=grant.user_id,
            dataset_id=grant.dataset_id,
            instrument_id=grant.instrument_id,
            market=grant.market,
            publication_id=grant.publication_id,
            capture_id=grant.capture_id,
            purpose=grant.purpose,
            valid_from=_as_utc(grant.valid_from),
            expires_at=_as_utc(grant.expires_at),
            revoked_at=revoked_at,
        )

    async def _load_source_grant(
        self,
        *,
        session: AsyncSession,
        scope: StockAnalysisSnapshotScope,
    ) -> SourceResearchGrantEvidence:
        statement = (
            select(StockSnapshotSourceResearchGrant)
            .where(
                StockSnapshotSourceResearchGrant.user_id == scope.user_id,
                StockSnapshotSourceResearchGrant.source_id == scope.source_id,
                StockSnapshotSourceResearchGrant.dataset_id == scope.dataset_id,
                StockSnapshotSourceResearchGrant.instrument_id == scope.instrument_id,
                StockSnapshotSourceResearchGrant.market == scope.market,
                StockSnapshotSourceResearchGrant.publication_id == scope.publication_id,
                StockSnapshotSourceResearchGrant.capture_id == scope.capture_id,
                StockSnapshotSourceResearchGrant.purpose == RESEARCH_PURPOSE,
            )
            .order_by(StockSnapshotSourceResearchGrant.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        grant = (await session.execute(statement)).scalar_one_or_none()
        if grant is None:
            raise StockDailySnapshotAuthorizationError("stock_daily_source_grant_missing")
        revoked_at, revocation_revision = await self._load_audit_state(
            session=session,
            source_grant_id=grant.id,
            subject_user_id=grant.user_id,
            grant_revision=grant.revision,
        )
        return SourceResearchGrantEvidence(
            grant_id=grant.id,
            revision=grant.revision,
            revocation_revision=revocation_revision,
            source_registry_revision=grant.source_registry_revision,
            user_id=grant.user_id,
            source_id=grant.source_id,
            dataset_id=grant.dataset_id,
            instrument_id=grant.instrument_id,
            market=grant.market,
            publication_id=grant.publication_id,
            capture_id=grant.capture_id,
            purpose=grant.purpose,
            valid_from=_as_utc(grant.valid_from),
            expires_at=_as_utc(grant.expires_at),
            revoked_at=revoked_at,
        )

    @staticmethod
    async def _load_audit_state(
        *,
        session: AsyncSession,
        subject_user_id: str,
        grant_revision: int,
        user_grant_id: str | None = None,
        source_grant_id: str | None = None,
    ) -> tuple[datetime | None, int]:
        """Require exactly one ISSUED and at most one later REVOKED event."""
        if (user_grant_id is None) == (source_grant_id is None):
            raise StockDailySnapshotAuthorizationError("stock_daily_grant_audit_invalid")
        statement = select(StockSnapshotGrantAudit).where(
            StockSnapshotGrantAudit.subject_user_id == subject_user_id,
            StockSnapshotGrantAudit.grant_revision == grant_revision,
        )
        if user_grant_id is not None:
            statement = statement.where(StockSnapshotGrantAudit.user_grant_id == user_grant_id)
        else:
            statement = statement.where(StockSnapshotGrantAudit.source_grant_id == source_grant_id)
        statement = statement.order_by(
            StockSnapshotGrantAudit.occurred_at.asc(),
            StockSnapshotGrantAudit.id.asc(),
        ).execution_options(populate_existing=True)
        audits = list((await session.execute(statement)).scalars())
        issued = [audit for audit in audits if audit.event_type == "ISSUED"]
        revoked = [audit for audit in audits if audit.event_type == "REVOKED"]
        if (
            len(issued) != 1
            or len(revoked) > 1
            or issued[0].revocation_revision != 1
            or (revoked and revoked[0].revocation_revision != 2)
            or {audit.event_type for audit in audits} - {"ISSUED", "REVOKED"}
        ):
            raise StockDailySnapshotAuthorizationError("stock_daily_grant_audit_invalid")
        if not revoked:
            return None, 1
        revoked_at = _as_utc(revoked[0].occurred_at)
        if revoked_at < _as_utc(issued[0].occurred_at):
            raise StockDailySnapshotAuthorizationError("stock_daily_grant_audit_invalid")
        return revoked_at, 2

    async def _load_source_registry(
        self,
        *,
        session: AsyncSession,
        scope: StockAnalysisSnapshotScope,
        principal: CurrentPrincipalEvidence,
        market_principal: MarketDataPrincipal,
    ) -> CurrentSourceRegistryEvidence:
        """Require the current registry row and its full source decision."""
        statement = (
            select(AssetDataSourceRegistry)
            .where(AssetDataSourceRegistry.source_id == SOURCE_ID)
            .execution_options(populate_existing=True)
        )
        registry = (await session.execute(statement)).scalar_one_or_none()
        if registry is None:
            raise StockDailySnapshotAuthorizationError("stock_daily_source_registry_unregistered")
        authorizer = MarketDataAccessAuthorizer(session, clock=self._clock)
        try:
            await authorizer.authorize_local_source(
                principal=market_principal,
                source_registry_id=SOURCE_ID,
                asset_type="stock",
                market=_REQUEST_MARKET_BY_POLICY_MARKET[scope.market],
                purpose="research",
            )
        except MarketDataAuthorizationError as exc:
            raise StockDailySnapshotAuthorizationError(
                "stock_daily_source_registry_denied"
            ) from exc
        return CurrentSourceRegistryEvidence(
            principal_user_id=principal.user_id,
            entitlement_revision=principal.entitlement_revision,
            source_id=SOURCE_ID,
            dataset_id=scope.dataset_id,
            market=scope.market,
            purpose=RESEARCH_PURPOSE,
            revision=source_registry_revision(registry),
            research_allowed=True,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise StockDailySnapshotAuthorizationError("stock_daily_clock_invalid")
        return value.astimezone(timezone.utc)


def source_registry_revision(registry: AssetDataSourceRegistry) -> str:
    """Return a stable revision string for the current registry row state.

    Grant issuers and this adapter must use the same helper so a source grant
    binds the exact registry decision available at issue time. The digest is
    unkeyed and identifies row state; it does not authenticate the registry.
    """
    if not isinstance(registry, AssetDataSourceRegistry):
        raise StockDailySnapshotAuthorizationError("stock_daily_source_registry_invalid")
    payload = {
        "version": _SOURCE_REGISTRY_REVISION_VERSION,
        "source_id": registry.source_id,
        "enabled": bool(registry.enabled),
        "asset_types": sorted(
            {_normalized(value) for value in (registry.asset_types or [])} - {""}
        ),
        "jurisdictions": sorted(
            {_normalized(value) for value in (registry.jurisdictions or [])} - {""}
        ),
        "license_status": _normalized(registry.license_status),
        "allowed_uses": sorted(
            {_normalized(value) for value in (registry.allowed_uses or [])} - {""}
        ),
        "redistribution_policy": _normalized(registry.redistribution_policy),
        "retention_policy": _normalized(registry.retention_policy),
        "effective_from": _as_utc(registry.effective_from).isoformat(),
        "effective_to": (
            _as_utc(registry.effective_to).isoformat()
            if registry.effective_to is not None
            else None
        ),
        "updated_at": _as_utc(registry.updated_at).isoformat(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{_SOURCE_REGISTRY_REVISION_VERSION}:{hashlib.sha256(encoded).hexdigest()}"


def _normalized(value: object) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def _as_utc(value: datetime) -> datetime:
    """Restore UTC awareness after SQLite returns a naive persisted datetime."""
    if not isinstance(value, datetime):
        raise StockDailySnapshotAuthorizationError("stock_daily_grant_timestamp_invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "DATASET_ID",
    "SOURCE_ID",
    "StockDailySnapshotAuthorizationAdapter",
    "StockDailySnapshotAuthorizationError",
    "source_registry_revision",
]
