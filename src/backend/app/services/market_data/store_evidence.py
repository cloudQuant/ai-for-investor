"""Validate source grants and provider registry state before and after I/O."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        AssetDataSourceRegistry,
        DgProvider,
        Mapping,
        MarketDataSourceAuthorization,
        MarketDataStore,
        MdSourceSnapshot,
        ProviderFetchResult,
        ResolvedMarketDataQueryContext,
        Sequence,
        _ValidatedSourceAuthorization,
        datetime,
    )


async def _require_active_provider(self: MarketDataStore, provider_id: str) -> DgProvider:
    from app.services.market_data.store import (
        DgProvider,
        MarketDataStoreError,
        select,
    )

    rows = list(
        (await self._db.execute(select(DgProvider).where(DgProvider.provider_id == provider_id)))
        .scalars()
        .all()
    )
    exact = [row for row in rows if row.provider_id == provider_id]
    if len(exact) != 1:
        raise MarketDataStoreError("PROVIDER_UNREGISTERED")
    if not exact[0].is_active:
        raise MarketDataStoreError("PROVIDER_INACTIVE")
    return exact[0]


async def ensure_provider_active(self: MarketDataStore, provider_id: str) -> None:
    """Authorize an expected receipt provider before a route invokes it.

    ``persist_provider_result`` repeats this check for the actual receipt,
    but performing it here prevents a revoked or unregistered paid source
    from receiving an outbound request merely to be rejected afterwards.
    """
    from app.services.market_data.store import (
        _require_text,
    )

    normalized = _require_text(provider_id, field_name="provider_id", maximum=255)
    await self._require_active_provider(normalized)


async def ensure_source_authorization_before_provider_io(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    source_authorization: MarketDataSourceAuthorization,
    *,
    provider_id: str,
    checked_at: datetime | None = None,
) -> None:
    """Revalidate one exact source grant before an external request starts.

    ``persist_provider_result`` repeats this validation after the provider
    responds, which closes the race between outbound I/O and durable
    receipt creation.  Scheduled collectors also need this preflight so a
    revoked, expired, or stale grant cannot trigger a paid/broad source
    request merely because its provider remains active.
    """
    from app.services.market_data.store import (
        _assert_writable_context,
        _require_aware_utc,
        _require_text,
    )

    _assert_writable_context(context)
    normalized_provider_id = _require_text(
        provider_id,
        field_name="provider_id",
        maximum=255,
    )
    local_checked_at = _require_aware_utc(
        checked_at or self._clock(),
        field_name="source authorization check timestamp",
    )
    await self._require_active_provider(normalized_provider_id)
    await self._validate_source_authorization_for_provider(
        context,
        provider_id=normalized_provider_id,
        source_authorization=source_authorization,
        local_received_at=local_checked_at,
        unverified_compatibility_reason=None,
    )


async def _validate_source_authorization(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    result: ProviderFetchResult,
    source_authorization: MarketDataSourceAuthorization | None,
    *,
    local_received_at: datetime,
    unverified_compatibility_reason: str | None,
) -> _ValidatedSourceAuthorization:
    """Validate a frozen source grant against the live registry before persistence.

    A normal v2 write must supply the grant.  The only bypass is a bounded,
    explicit compatibility reason, which produces a permanently
    unverified receipt that v2 local reads reject.  Once a grant is
    supplied this method accepts neither an arbitrary mapping nor a
    caller-computed descriptor alone: it verifies the typed evidence, its
    canonical digest, request context, and the current registry row before
    the source snapshot can be staged.
    """
    return await self._validate_source_authorization_for_provider(
        context,
        provider_id=result.provider_id,
        source_authorization=source_authorization,
        local_received_at=local_received_at,
        unverified_compatibility_reason=unverified_compatibility_reason,
    )


async def _validate_source_authorization_for_provider(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    provider_id: str,
    source_authorization: MarketDataSourceAuthorization | None,
    local_received_at: datetime,
    unverified_compatibility_reason: str | None,
) -> _ValidatedSourceAuthorization:
    """Validate one source grant using its explicit provider identity."""
    from app.services.market_data.store import (
        _UNVERIFIED_COMPATIBILITY_PROVENANCE_VERSION,
        SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY,
        SOURCE_AUTHORIZATION_STATE_VERIFIED,
        AssetDataSourceRegistry,
        MappingProxyType,
        MarketDataStoreError,
        _assert_source_authorization_matches_registry,
        _normalize_unverified_compatibility_reason,
        _normalized_source_authorization_provenance,
        _ValidatedSourceAuthorization,
        select,
    )

    if source_authorization is None:
        reason = _normalize_unverified_compatibility_reason(unverified_compatibility_reason)
        return _ValidatedSourceAuthorization(
            state=SOURCE_AUTHORIZATION_STATE_UNVERIFIED_COMPATIBILITY,
            descriptor_sha256=None,
            provenance=MappingProxyType(
                {
                    "version": _UNVERIFIED_COMPATIBILITY_PROVENANCE_VERSION,
                    "reason": reason,
                    "decision": "UNVERIFIED",
                }
            ),
        )
    if unverified_compatibility_reason is not None:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_MODE_CONFLICT")
    provenance = _normalized_source_authorization_provenance(
        context,
        source_authorization,
        provider_id=provider_id,
    )
    # Re-read rather than use ``Session.get``: a long-lived request
    # session may already have an identity-mapped registry row from an
    # earlier control-plane lookup.  The query service owns any short
    # write authorization lock; this is the independent post-query
    # freshness/integrity check without taking a second lock.
    registry = await self._db.scalar(
        select(AssetDataSourceRegistry)
        .where(AssetDataSourceRegistry.source_id == provenance["source_registry_id"])
        .execution_options(populate_existing=True)
    )
    if registry is None:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_UNREGISTERED")
    _assert_source_authorization_matches_registry(
        provenance,
        registry,
        local_received_at=local_received_at,
    )
    return _ValidatedSourceAuthorization(
        state=SOURCE_AUTHORIZATION_STATE_VERIFIED,
        descriptor_sha256=str(provenance["descriptor_hash"]),
        provenance=MappingProxyType(provenance),
    )


def _normalized_source_authorization_provenance(
    context: ResolvedMarketDataQueryContext,
    source_authorization: MarketDataSourceAuthorization,
    *,
    provider_id: str,
) -> dict[str, object]:
    """Return a canonical authorization receipt mapping for store validation.

    The persistence API intentionally does not accept a free-form mapping.  A
    real ``MarketDataSourceAuthorization`` must identify the actual provider,
    match the resolved query dimensions, state an ALLOW decision, and carry a
    digest recomputed from every persisted authorization field.  The digest is
    an integrity binding, not a cryptographic signature: the store separately
    compares the frozen fields with the current registry.  Public v2 callers
    obtain this typed DTO from the access authorizer before reaching this
    internal persistence boundary.
    """
    from app.services.market_data.store import (
        _SOURCE_AUTHORIZATION_ALLOWED_USES,
        _SOURCE_AUTHORIZATION_VERSION,
        MarketDataSourceAuthorization,
        MarketDataStoreError,
        _canonical_json,
        _require_authorization_lower,
        _require_authorization_tokens,
        _require_authorization_upper,
        _require_optional_utc_authorization_timestamp,
        _require_sha256_digest,
        _require_text,
        _require_utc_authorization_timestamp,
        _sha256,
    )

    if type(source_authorization) is not MarketDataSourceAuthorization:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")

    source_registry_id = _require_text(
        source_authorization.source_registry_id,
        field_name="source_registry_id",
        maximum=255,
    )
    normalized_provider_id = _require_text(provider_id, field_name="provider_id", maximum=255)
    if source_registry_id != normalized_provider_id:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_PROVIDER_MISMATCH")

    asset_type = _require_authorization_lower(
        source_authorization.asset_type,
        field_name="source authorization asset_type",
        maximum=32,
    )
    market = _require_authorization_upper(
        source_authorization.market,
        field_name="source authorization market",
        maximum=128,
    )
    purpose = _require_authorization_lower(
        source_authorization.purpose,
        field_name="source authorization purpose",
        maximum=32,
    )
    venue = context.identity.venue
    if (
        venue is None
        or asset_type != context.identity.asset_type
        or market != venue
        or purpose != context.query.purpose
    ):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_CONTEXT_MISMATCH")
    if purpose not in _SOURCE_AUTHORIZATION_ALLOWED_USES:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_CONTEXT_MISMATCH")

    authorization: dict[str, object] = {
        "source_registry_id": source_registry_id,
        "registry_updated_at": _require_utc_authorization_timestamp(
            source_authorization.registry_updated_at,
            field_name="source authorization registry_updated_at",
        ),
        "asset_type": asset_type,
        "market": market,
        "purpose": purpose,
        "license_status": _require_authorization_upper(
            source_authorization.license_status,
            field_name="source authorization license_status",
            maximum=64,
        ),
        "allowed_uses": list(
            _require_authorization_tokens(
                source_authorization.allowed_uses,
                field_name="source authorization allowed_uses",
            )
        ),
        "jurisdictions": list(
            _require_authorization_tokens(
                source_authorization.jurisdictions,
                field_name="source authorization jurisdictions",
            )
        ),
        "effective_from": _require_utc_authorization_timestamp(
            source_authorization.effective_from,
            field_name="source authorization effective_from",
        ),
        "effective_to": _require_optional_utc_authorization_timestamp(
            source_authorization.effective_to,
            field_name="source authorization effective_to",
        ),
        "retention_policy": _require_authorization_upper(
            source_authorization.retention_policy,
            field_name="source authorization retention_policy",
            maximum=64,
        ),
        "retention_expires_at": _require_optional_utc_authorization_timestamp(
            source_authorization.retention_expires_at,
            field_name="source authorization retention_expires_at",
        ),
        "redistribution_policy": _require_authorization_upper(
            source_authorization.redistribution_policy,
            field_name="source authorization redistribution_policy",
            maximum=64,
        ),
        "principal_scope": _require_text(
            source_authorization.principal_scope,
            field_name="source authorization principal_scope",
            maximum=256,
        ),
        "tenant_scope": _require_text(
            source_authorization.tenant_scope,
            field_name="source authorization tenant_scope",
            maximum=256,
        ),
        "entitlement_revision": _require_sha256_digest(
            source_authorization.entitlement_revision,
            code="SOURCE_AUTHORIZATION_INVALID",
        ),
        "decision": source_authorization.decision,
    }
    if authorization["decision"] != "ALLOW":
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_DENIED")
    descriptor_hash = _require_sha256_digest(
        source_authorization.descriptor_hash,
        code="SOURCE_AUTHORIZATION_INVALID",
    )
    descriptor_payload = {
        "version": _SOURCE_AUTHORIZATION_VERSION,
        **authorization,
    }
    computed_descriptor_hash = _sha256(
        _canonical_json(
            descriptor_payload,
            field_name="source authorization descriptor",
        )
    )
    if descriptor_hash != computed_descriptor_hash:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_DESCRIPTOR_MISMATCH")
    authorization["descriptor_hash"] = descriptor_hash
    return authorization


def _assert_source_authorization_matches_registry(
    authorization: Mapping[str, object],
    registry: AssetDataSourceRegistry,
    *,
    local_received_at: datetime,
) -> None:
    """Refuse persistence if the supplied authorization is stale or unlicensed.

    Authorization is first evaluated at the query boundary before a local read
    or provider call.  This independent check closes the race between that
    evaluation and immutable receipt persistence by comparing every frozen
    registry field against a freshly loaded current row.  It is not a
    cryptographic trust boundary against code already running in this process.
    """
    from app.services.market_data.store import (
        _SOURCE_AUTHORIZATION_ALLOWED_USES,
        _SOURCE_AUTHORIZATION_APPROVED_LICENSES,
        _SOURCE_AUTHORIZATION_PROHIBITED_RETENTION_POLICIES,
        _SOURCE_AUTHORIZATION_READABLE_REDISTRIBUTION_POLICIES,
        MarketDataStoreError,
        _parse_authorization_timestamp,
        _parse_optional_authorization_timestamp,
        _registry_authorization_fields,
        _registry_authorization_tokens,
        _require_aware_utc,
        _source_authorization_jurisdiction_allows,
    )

    if not registry.enabled:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    expected = _registry_authorization_fields(registry)
    for field_name, expected_value in expected.items():
        if authorization.get(field_name) != expected_value:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_STALE")

    asset_type = str(authorization["asset_type"])
    market = str(authorization["market"])
    purpose = str(authorization["purpose"])
    if asset_type.upper() not in _registry_authorization_tokens(
        registry.asset_types,
        field_name="registry asset_types",
    ):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    if authorization["license_status"] not in _SOURCE_AUTHORIZATION_APPROVED_LICENSES:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    raw_allowed_uses = authorization["allowed_uses"]
    if not isinstance(raw_allowed_uses, (list, tuple)):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    allowed_uses = frozenset(str(value) for value in raw_allowed_uses)
    if not (_SOURCE_AUTHORIZATION_ALLOWED_USES[purpose] & allowed_uses):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    raw_jurisdictions = authorization["jurisdictions"]
    if not isinstance(raw_jurisdictions, (list, tuple)):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    jurisdictions = tuple(str(value) for value in raw_jurisdictions)
    if not _source_authorization_jurisdiction_allows(jurisdictions, market):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    if authorization["retention_policy"] in _SOURCE_AUTHORIZATION_PROHIBITED_RETENTION_POLICIES:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    if (
        authorization["redistribution_policy"]
        not in _SOURCE_AUTHORIZATION_READABLE_REDISTRIBUTION_POLICIES
    ):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")

    at = _require_aware_utc(local_received_at, field_name="local receipt timestamp")
    effective_from = _parse_authorization_timestamp(
        str(authorization["effective_from"]),
        field_name="source authorization effective_from",
    )
    effective_to = _parse_optional_authorization_timestamp(
        authorization["effective_to"],
        field_name="source authorization effective_to",
    )
    retention_expires_at = _parse_optional_authorization_timestamp(
        authorization["retention_expires_at"],
        field_name="source authorization retention_expires_at",
    )
    if effective_from > at or (effective_to is not None and effective_to < at):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")
    if retention_expires_at is not None and retention_expires_at < at:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_DENIED")


def _source_authorization_receipt_purpose_allows_read(
    *,
    receipt_purpose: str,
    query_purpose: str,
) -> bool:
    """Return whether a frozen collection purpose may satisfy this local read.

    Current principal and source authorization are evaluated separately before
    this verifier runs.  This compatibility rule therefore only controls how
    a sealed receipt is reused, and contains the sole audited exception from
    exact purpose matching: ``research_cache_fill`` may serve ``research``.
    """
    from app.services.market_data.store import (
        _SOURCE_AUTHORIZATION_RECEIPT_PURPOSES_BY_QUERY_PURPOSE,
    )

    return receipt_purpose in _SOURCE_AUTHORIZATION_RECEIPT_PURPOSES_BY_QUERY_PURPOSE.get(
        query_purpose,
        frozenset(),
    )


def _verified_source_authorization_registry_id(
    snapshot: MdSourceSnapshot,
    *,
    context: ResolvedMarketDataQueryContext,
) -> str:
    """Validate frozen authorization evidence before a v2 local read uses it.

    The relational state filters legacy and compatibility rows in SQL.  This
    verifier then binds a verified state to its canonical provenance, immutable
    source identifier, and the query's asset/market/purpose dimensions.  It is
    an integrity check for persisted evidence, not a cryptographic signature
    against trusted code already running inside this process.
    """
    from app.services.market_data.store import (
        _SOURCE_AUTHORIZATION_ALLOWED_USES,
        _SOURCE_AUTHORIZATION_APPROVED_LICENSES,
        _SOURCE_AUTHORIZATION_PROHIBITED_RETENTION_POLICIES,
        _SOURCE_AUTHORIZATION_PROVENANCE_FIELDS,
        _SOURCE_AUTHORIZATION_READABLE_REDISTRIBUTION_POLICIES,
        _SOURCE_AUTHORIZATION_VERSION,
        SOURCE_AUTHORIZATION_STATE_VERIFIED,
        MarketDataStoreError,
        _canonical_json,
        _json_safe_mapping,
        _parse_authorization_timestamp,
        _parse_optional_authorization_timestamp,
        _require_authorization_lower,
        _require_authorization_upper,
        _require_optional_utc_authorization_timestamp,
        _require_persisted_authorization_tokens,
        _require_sha256_digest,
        _require_text,
        _require_utc_authorization_timestamp,
        _sha256,
        _source_authorization_jurisdiction_allows,
        _source_authorization_receipt_purpose_allows_read,
        _stored_utc,
    )

    if snapshot.source_authorization_state != SOURCE_AUTHORIZATION_STATE_VERIFIED:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_UNVERIFIED")
    try:
        descriptor_sha256 = _require_sha256_digest(
            snapshot.source_authorization_descriptor_sha256,
            code="SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY",
        )
        snapshot_source_id = _require_text(
            snapshot.source_id,
            field_name="source snapshot source_id",
            maximum=255,
        )
        provenance = _json_safe_mapping(
            snapshot.provenance_json,
            field_name="source snapshot provenance",
        )
        authorization = _json_safe_mapping(
            provenance.get("source_authorization"),
            field_name="source authorization provenance",
        )
        if set(authorization) != _SOURCE_AUTHORIZATION_PROVENANCE_FIELDS:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        persisted_descriptor = authorization.pop("descriptor_hash")
        if persisted_descriptor != descriptor_sha256:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        canonical_descriptor = _sha256(
            _canonical_json(
                {"version": _SOURCE_AUTHORIZATION_VERSION, **authorization},
                field_name="source authorization provenance",
            )
        )
        if canonical_descriptor != descriptor_sha256:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")

        source_registry_id = _require_text(
            authorization["source_registry_id"],
            field_name="source authorization source_registry_id",
            maximum=255,
        )
        if source_registry_id != snapshot_source_id:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        asset_type = _require_authorization_lower(
            authorization["asset_type"],
            field_name="source authorization asset_type",
            maximum=32,
        )
        market = _require_authorization_upper(
            authorization["market"],
            field_name="source authorization market",
            maximum=128,
        )
        purpose = _require_authorization_lower(
            authorization["purpose"],
            field_name="source authorization purpose",
            maximum=32,
        )
        venue = context.identity.venue
        if (
            venue is None
            or asset_type != context.identity.asset_type
            or market != venue
            or not _source_authorization_receipt_purpose_allows_read(
                receipt_purpose=purpose,
                query_purpose=context.query.purpose,
            )
            or purpose not in _SOURCE_AUTHORIZATION_ALLOWED_USES
        ):
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")

        _require_utc_authorization_timestamp(
            authorization["registry_updated_at"],
            field_name="source authorization registry_updated_at",
        )
        license_status = _require_authorization_upper(
            authorization["license_status"],
            field_name="source authorization license_status",
            maximum=64,
        )
        allowed_uses = _require_persisted_authorization_tokens(
            authorization["allowed_uses"],
            field_name="source authorization allowed_uses",
        )
        jurisdictions = _require_persisted_authorization_tokens(
            authorization["jurisdictions"],
            field_name="source authorization jurisdictions",
        )
        effective_from = _parse_authorization_timestamp(
            _require_utc_authorization_timestamp(
                authorization["effective_from"],
                field_name="source authorization effective_from",
            ),
            field_name="source authorization effective_from",
        )
        effective_to_value = _require_optional_utc_authorization_timestamp(
            authorization["effective_to"],
            field_name="source authorization effective_to",
        )
        effective_to = _parse_optional_authorization_timestamp(
            effective_to_value,
            field_name="source authorization effective_to",
        )
        retention_policy = _require_authorization_upper(
            authorization["retention_policy"],
            field_name="source authorization retention_policy",
            maximum=64,
        )
        retention_expires_at_value = _require_optional_utc_authorization_timestamp(
            authorization["retention_expires_at"],
            field_name="source authorization retention_expires_at",
        )
        retention_expires_at = _parse_optional_authorization_timestamp(
            retention_expires_at_value,
            field_name="source authorization retention_expires_at",
        )
        redistribution_policy = _require_authorization_upper(
            authorization["redistribution_policy"],
            field_name="source authorization redistribution_policy",
            maximum=64,
        )
        _require_text(
            authorization["principal_scope"],
            field_name="source authorization principal_scope",
            maximum=256,
        )
        _require_text(
            authorization["tenant_scope"],
            field_name="source authorization tenant_scope",
            maximum=256,
        )
        _require_sha256_digest(
            authorization["entitlement_revision"],
            code="SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY",
        )
        if authorization["decision"] != "ALLOW":
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        if (
            license_status not in _SOURCE_AUTHORIZATION_APPROVED_LICENSES
            or not (_SOURCE_AUTHORIZATION_ALLOWED_USES[purpose] & frozenset(allowed_uses))
            or not _source_authorization_jurisdiction_allows(jurisdictions, market)
            or retention_policy in _SOURCE_AUTHORIZATION_PROHIBITED_RETENTION_POLICIES
            or redistribution_policy not in _SOURCE_AUTHORIZATION_READABLE_REDISTRIBUTION_POLICIES
        ):
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        receipt_at = _stored_utc(snapshot.retrieved_at, field_name="source snapshot retrieved_at")
        if effective_from > receipt_at or (effective_to is not None and effective_to < receipt_at):
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
        if retention_expires_at is not None and retention_expires_at < receipt_at:
            raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
    except (KeyError, TypeError, ValueError, MarketDataStoreError) as exc:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY") from exc
    return source_registry_id


def _registry_authorization_fields(registry: AssetDataSourceRegistry) -> dict[str, object]:
    """Normalize exactly the registry dimensions frozen into a receipt."""
    from app.services.market_data.store import (
        _normalized_registry_authorization_token,
        _registry_authorization_tokens,
        _require_authorization_upper,
        _require_text,
        _stored_utc,
    )

    return {
        "source_registry_id": _require_text(
            registry.source_id,
            field_name="registry source_id",
            maximum=255,
        ),
        "registry_updated_at": _stored_utc(
            registry.updated_at,
            field_name="registry updated_at",
        ).isoformat(),
        "license_status": _require_authorization_upper(
            _normalized_registry_authorization_token(
                registry.license_status,
                field_name="registry license_status",
                maximum=64,
            ),
            field_name="registry license_status",
            maximum=64,
        ),
        "allowed_uses": list(
            _registry_authorization_tokens(
                registry.allowed_uses,
                field_name="registry allowed_uses",
            )
        ),
        "jurisdictions": list(
            _registry_authorization_tokens(
                registry.jurisdictions,
                field_name="registry jurisdictions",
            )
        ),
        "effective_from": _stored_utc(
            registry.effective_from,
            field_name="registry effective_from",
        ).isoformat(),
        "effective_to": (
            _stored_utc(registry.effective_to, field_name="registry effective_to").isoformat()
            if registry.effective_to is not None
            else None
        ),
        "retention_policy": _require_authorization_upper(
            _normalized_registry_authorization_token(
                registry.retention_policy,
                field_name="registry retention_policy",
                maximum=64,
            ),
            field_name="registry retention_policy",
            maximum=64,
        ),
        "retention_expires_at": (
            _stored_utc(
                registry.retention_expires_at,
                field_name="registry retention_expires_at",
            ).isoformat()
            if registry.retention_expires_at is not None
            else None
        ),
        "redistribution_policy": _require_authorization_upper(
            _normalized_registry_authorization_token(
                registry.redistribution_policy,
                field_name="registry redistribution_policy",
                maximum=64,
            ),
            field_name="registry redistribution_policy",
            maximum=64,
        ),
    }


def _require_authorization_tokens(value: object, *, field_name: str) -> tuple[str, ...]:
    """Require the immutable tuple shape emitted by the authorization boundary."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_authorization_upper,
    )

    if not isinstance(value, tuple):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    normalized = tuple(
        _require_authorization_upper(item, field_name=field_name, maximum=128) for item in value
    )
    if not normalized or normalized != tuple(sorted(set(normalized))):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    return normalized


def _require_persisted_authorization_tokens(value: object, *, field_name: str) -> tuple[str, ...]:
    """Require the canonical JSON list stored from an authorization receipt."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_authorization_upper,
    )

    if not isinstance(value, list):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
    normalized = tuple(
        _require_authorization_upper(item, field_name=field_name, maximum=128) for item in value
    )
    if not normalized or normalized != tuple(sorted(set(normalized))):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_RECEIPT_INTEGRITY")
    return normalized


def _registry_authorization_tokens(value: object, *, field_name: str) -> tuple[str, ...]:
    """Normalize a registry JSON list without accepting a free-form scalar."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _normalized_registry_authorization_token,
    )

    if not isinstance(value, (list, tuple)):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_INVALID")
    normalized = tuple(
        sorted(
            {
                _normalized_registry_authorization_token(
                    item,
                    field_name=field_name,
                    maximum=128,
                )
                for item in value
            }
        )
    )
    if not normalized:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REGISTRY_INVALID")
    return normalized


def _normalized_registry_authorization_token(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> str:
    """Normalize registry text just as the authorization boundary does."""
    from app.services.market_data.store import (
        _require_text,
    )

    return _require_text(value, field_name=field_name, maximum=maximum).upper()


def _require_authorization_lower(value: object, *, field_name: str, maximum: int) -> str:
    """Require a canonical lowercase authorization token."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_text,
    )

    normalized = _require_text(value, field_name=field_name, maximum=maximum)
    if normalized != normalized.lower():
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    return normalized


def _require_authorization_upper(value: object, *, field_name: str, maximum: int) -> str:
    """Require a canonical uppercase authorization token."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_text,
    )

    normalized = _require_text(value, field_name=field_name, maximum=maximum)
    if normalized != normalized.upper():
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    return normalized


def _require_utc_authorization_timestamp(value: object, *, field_name: str) -> str:
    """Require the canonical UTC ISO-8601 form emitted by the authorizer."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _parse_authorization_timestamp,
    )

    parsed = _parse_authorization_timestamp(value, field_name=field_name)
    canonical = parsed.isoformat()
    if value != canonical:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    return canonical


def _require_optional_utc_authorization_timestamp(
    value: object,
    *,
    field_name: str,
) -> str | None:
    from app.services.market_data.store import (
        _require_utc_authorization_timestamp,
    )

    if value is None:
        return None
    return _require_utc_authorization_timestamp(value, field_name=field_name)


def _parse_authorization_timestamp(value: object, *, field_name: str) -> datetime:
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_aware_utc,
        datetime,
    )

    if not isinstance(value, str):
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_INVALID") from exc
    return _require_aware_utc(parsed, field_name=field_name)


def _parse_optional_authorization_timestamp(value: object, *, field_name: str) -> datetime | None:
    from app.services.market_data.store import (
        _parse_authorization_timestamp,
    )

    if value is None:
        return None
    return _parse_authorization_timestamp(value, field_name=field_name)


def _source_authorization_jurisdiction_allows(jurisdictions: Sequence[str], market: str) -> bool:
    """Apply the registry's global, venue, and country-prefix market rules."""
    if "GLOBAL" in jurisdictions:
        return True
    market_prefix = market.split("-", maxsplit=1)[0]
    return market in jurisdictions or market_prefix in jurisdictions


def _normalize_unverified_compatibility_reason(value: object) -> str:
    """Require a deliberately named, narrowly scoped no-grant write path."""
    from app.services.market_data.store import (
        _UNVERIFIED_COMPATIBILITY_REASONS,
        MarketDataStoreError,
        _require_text,
    )

    if value is None:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REQUIRED")
    normalized = _require_text(
        value,
        field_name="unverified compatibility reason",
        maximum=64,
    )
    if normalized not in _UNVERIFIED_COMPATIBILITY_REASONS:
        raise MarketDataStoreError("SOURCE_AUTHORIZATION_REQUIRED")
    return normalized
