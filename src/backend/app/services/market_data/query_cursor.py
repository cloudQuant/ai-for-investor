"""Signed cursor tokens and replay-safe pagination for market-data queries."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.services.market_data.access import MarketDataQueryAccess
from app.services.market_data.publication import MarketDataVisibilityAnchor
from app.services.market_data.source_policy import MarketDataSourcePolicy
from app.services.market_data.store import LocalObservationRevision

UTC = timezone.utc
_CURSOR_HMAC_DIGEST_BYTES = hashlib.sha256().digest_size
_MAX_CURSOR_TOKEN_LENGTH = 2048
# A request accepts cursor tokens up to 2048 characters. Accounting for the
# fixed HMAC segment leaves 1503 URL-safe payload bytes; retain a small margin
# so a token emitted here is always acceptable to the request schema.
_MAX_CURSOR_PAYLOAD_BYTES = 1500
_CURSOR_VERSION = 3
_DEFAULT_CURSOR_TTL = timedelta(minutes=15)
_UNBOUND_CURSOR_PRINCIPAL_SCOPE = "unbound"
_UNBOUND_CURSOR_TENANT_SCOPE = "unbound"
_UNBOUND_CURSOR_ENTITLEMENT_REVISION = "unbound-v1"
_BASE64URL_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


class MarketDataQueryServiceError(ValueError):
    """Stable error code for a local-first orchestration boundary failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MarketDataCursorBinding:
    """Caller-provided auth/policy dimensions signed into a pagination token.

    This module deliberately does not decide authorization. The API layer can
    provide the currently authenticated principal and entitlement revision,
    and a future immutable policy registry can provide its descriptor hash.
    Until that integration is enabled, the explicit unbound sentinel preserves
    the disabled v2 compatibility path without silently omitting token fields.
    """

    principal_scope: str = _UNBOUND_CURSOR_PRINCIPAL_SCOPE
    tenant_scope: str = _UNBOUND_CURSOR_TENANT_SCOPE
    entitlement_revision: str = _UNBOUND_CURSOR_ENTITLEMENT_REVISION
    policy_descriptor_hash: str | None = None
    access_grant_descriptor_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.principal_scope, field_name="cursor principal scope", maximum=256)
        _require_text(self.tenant_scope, field_name="cursor tenant scope", maximum=256)
        _require_text(
            self.entitlement_revision,
            field_name="cursor entitlement revision",
            maximum=128,
        )
        if self.policy_descriptor_hash is not None:
            _require_sha256(
                self.policy_descriptor_hash,
                field_name="cursor policy descriptor hash",
            )
        if self.access_grant_descriptor_hash is not None:
            _require_sha256(
                self.access_grant_descriptor_hash,
                field_name="cursor access grant descriptor hash",
            )

    def with_policy_descriptor_hash(self, policy_descriptor_hash: str) -> MarketDataCursorBinding:
        """Bind the caller scope to the resolved immutable policy descriptor."""
        _require_sha256(policy_descriptor_hash, field_name="cursor policy descriptor hash")
        if (
            self.policy_descriptor_hash is not None
            and self.policy_descriptor_hash != policy_descriptor_hash
        ):
            raise MarketDataQueryServiceError("CURSOR_POLICY_MISMATCH")
        return replace(self, policy_descriptor_hash=policy_descriptor_hash)

    def with_access_grant_descriptor_hash(
        self,
        access_grant_descriptor_hash: str,
    ) -> MarketDataCursorBinding:
        """Bind a cursor to the current principal's source-registry decision.

        The server-owned source-policy hash and the access-grant hash have
        distinct meanings. The former is available before identity resolution;
        the latter is recomputed only after the exact asset/market and current
        source registry have been evaluated.
        """
        _require_sha256(
            access_grant_descriptor_hash,
            field_name="cursor access grant descriptor hash",
        )
        if (
            self.access_grant_descriptor_hash is not None
            and self.access_grant_descriptor_hash != access_grant_descriptor_hash
        ):
            raise MarketDataQueryServiceError("CURSOR_ACCESS_GRANT_MISMATCH")
        return replace(self, access_grant_descriptor_hash=access_grant_descriptor_hash)


@dataclass(frozen=True, slots=True)
class _CursorBindingDigest:
    """Fixed-size access dimensions stored in an issued cursor payload.

    Raw principal and tenant values can be long or contain Unicode. Keeping
    their domain-separated SHA-256 digests in a token preserves exact replay
    binding without exposing those identifiers or making a valid authenticated
    scope exceed the public cursor length limit.
    """

    principal_scope_sha256: str
    tenant_scope_sha256: str
    entitlement_revision_sha256: str
    policy_descriptor_hash: str
    access_grant_descriptor_hash: str | None

    def __post_init__(self) -> None:
        _require_sha256(
            self.principal_scope_sha256,
            field_name="cursor principal scope hash",
        )
        _require_sha256(
            self.tenant_scope_sha256,
            field_name="cursor tenant scope hash",
        )
        _require_sha256(
            self.entitlement_revision_sha256,
            field_name="cursor entitlement revision hash",
        )
        _require_sha256(
            self.policy_descriptor_hash,
            field_name="cursor policy descriptor hash",
        )
        if self.access_grant_descriptor_hash is not None:
            _require_sha256(
                self.access_grant_descriptor_hash,
                field_name="cursor access grant descriptor hash",
            )


@dataclass(frozen=True, slots=True)
class _Cursor:
    """An authenticated-by-content pagination anchor and frozen local cutoff."""

    query_fingerprint: str
    key: tuple[str, str]
    visibility_anchor: MarketDataVisibilityAnchor
    identity_visibility_anchor: MarketDataVisibilityAnchor
    binding: _CursorBindingDigest
    issued_at: datetime
    expires_at: datetime


def _binding_for_access(
    *,
    cursor_binding: MarketDataCursorBinding | None,
    access: MarketDataQueryAccess | None,
) -> MarketDataCursorBinding:
    """Build one cursor binding from the current authenticated execution.

    A public caller must not be able to supply a cursor scope for another
    principal. When access is present, the only accepted unbound dimensions
    are the exact values derived from the principal that the API just
    authenticated. Policy and grant hashes remain server-owned and are set
    later in this execution.
    """
    if access is None:
        return cursor_binding or MarketDataCursorBinding()
    expected = MarketDataCursorBinding(
        principal_scope=access.principal.principal_scope,
        tenant_scope=access.principal.tenant_scope,
        entitlement_revision=access.principal.entitlement_revision,
    )
    if cursor_binding is None:
        return expected
    if (
        cursor_binding.principal_scope != expected.principal_scope
        or cursor_binding.tenant_scope != expected.tenant_scope
        or cursor_binding.entitlement_revision != expected.entitlement_revision
        or cursor_binding.policy_descriptor_hash is not None
        or cursor_binding.access_grant_descriptor_hash is not None
    ):
        raise MarketDataQueryServiceError("CURSOR_ACCESS_CONTEXT_MISMATCH")
    return expected


def _policy_descriptor_hash(policy: MarketDataSourcePolicy) -> str:
    """Hash only the immutable, reviewed policy dimensions a cursor must replay.

    Provider adapters deliberately stay out of this document because they are
    process objects. Their registered route capability and priority are what
    determine whether a request was authorized for a route.
    """
    descriptor = {
        "policy_id": policy.policy_id,
        "allowed_purposes": sorted(policy.allowed_purposes),
        "routes": [
            {
                "route_id": route.route_id,
                "request_provider": route.request_provider,
                "expected_result_provider_ids": sorted(route.expected_result_provider_ids),
                "asset_types": sorted(route.asset_types),
                "data_kinds": sorted(route.data_kinds),
                "frequencies": sorted(route.frequencies),
                "markets": sorted(route.markets),
                "adjustments": _policy_axis_payload(route.adjustments),
                "price_bases": _policy_axis_payload(route.price_bases),
                "currencies": _policy_axis_payload(route.currencies),
                "units": _policy_axis_payload(route.units),
                "family_id": route.family_id,
                "family_contract_version": route.family_contract_version,
                "provider_endpoint": route.provider_endpoint,
                "product_types": (
                    sorted(route.product_types) if route.product_types is not None else None
                ),
                "fund_identity_kinds": (
                    sorted(route.fund_identity_kinds)
                    if route.fund_identity_kinds is not None
                    else None
                ),
            }
            for route in policy.routes
        ],
        "local_sources": [
            {
                "local_source_id": local_source.local_source_id,
                "source_registry_id": local_source.source_registry_id,
                "asset_types": sorted(local_source.asset_types),
                "data_kinds": sorted(local_source.data_kinds),
                "frequencies": sorted(local_source.frequencies),
                "markets": sorted(local_source.markets),
                "adjustments": _policy_axis_payload(local_source.adjustments),
                "price_bases": _policy_axis_payload(local_source.price_bases),
                "currencies": _policy_axis_payload(local_source.currencies),
                "units": _policy_axis_payload(local_source.units),
                "family_id": local_source.family_id,
                "family_contract_version": local_source.family_contract_version,
                "product_types": (
                    sorted(local_source.product_types)
                    if local_source.product_types is not None
                    else None
                ),
                "fund_identity_kinds": (
                    sorted(local_source.fund_identity_kinds)
                    if local_source.fund_identity_kinds is not None
                    else None
                ),
            }
            for local_source in policy.local_sources
        ],
    }
    # A reviewed policy may legitimately have several routes. It is hashed
    # before it becomes the fixed-size cursor field, so policy canonicalization
    # must not inherit the much smaller transport-token size limit.
    return hashlib.sha256(_canonical_json_bytes(descriptor)).hexdigest()


def _policy_axis_payload(values: frozenset[str | None]) -> list[str | None]:
    """Canonicalize capability axes which intentionally permit an explicit null."""
    return sorted(values, key=lambda item: (item is not None, item or ""))


def _paginate_observations(
    observations: tuple[LocalObservationRevision, ...],
    *,
    cursor: _Cursor | None,
    page_size: int,
    query_fingerprint: str,
    visibility_anchor: MarketDataVisibilityAnchor,
    identity_visibility_anchor: MarketDataVisibilityAnchor,
    binding: MarketDataCursorBinding,
    issued_at: datetime,
    expires_at: datetime,
    signing_key_supplier: Callable[[], bytes],
) -> tuple[tuple[LocalObservationRevision, ...], str | None]:
    """Validate the frozen replay boundary and produce one cursor page."""
    start_index = 0
    if cursor is not None:
        if cursor.query_fingerprint != query_fingerprint:
            raise MarketDataQueryServiceError("CURSOR_QUERY_MISMATCH")
        if cursor.visibility_anchor != visibility_anchor:
            raise MarketDataQueryServiceError("CURSOR_VISIBILITY_ANCHOR_MISMATCH")
        if cursor.identity_visibility_anchor != identity_visibility_anchor:
            raise MarketDataQueryServiceError("CURSOR_IDENTITY_ANCHOR_MISMATCH")
        if cursor.binding != _cursor_binding_digest(binding):
            raise MarketDataQueryServiceError("CURSOR_ACCESS_MISMATCH")
        for index, item in enumerate(observations):
            if _observation_cursor_key(item) == cursor.key:
                start_index = index + 1
                break
        else:
            raise MarketDataQueryServiceError("CURSOR_NOT_FOUND")
    page = observations[start_index : start_index + page_size]
    if start_index + len(page) >= len(observations) or not page:
        return page, None
    return page, _encode_cursor(
        _observation_cursor_key(page[-1]),
        query_fingerprint=query_fingerprint,
        visibility_anchor=visibility_anchor,
        identity_visibility_anchor=identity_visibility_anchor,
        binding=binding,
        issued_at=issued_at,
        expires_at=expires_at,
        signing_key=signing_key_supplier(),
    )


def _observation_cursor_key(item: LocalObservationRevision) -> tuple[str, str]:
    return item.event_at.isoformat(), item.revision_id


def _encode_cursor(
    key: tuple[str, str],
    *,
    query_fingerprint: str,
    visibility_anchor: MarketDataVisibilityAnchor,
    identity_visibility_anchor: MarketDataVisibilityAnchor,
    binding: MarketDataCursorBinding,
    issued_at: datetime,
    expires_at: datetime,
    signing_key: bytes,
) -> str:
    _require_sha256(query_fingerprint, field_name="cursor query fingerprint")
    _require_text(key[1], field_name="cursor revision_id", maximum=255)
    parsed_event_at = _parse_cursor_datetime(key[0], field_name="cursor event_at")
    normalized_issued_at = _normalize_cursor_datetime(issued_at, field_name="cursor issued_at")
    normalized_expires_at = _normalize_cursor_datetime(expires_at, field_name="cursor expires_at")
    if normalized_expires_at <= normalized_issued_at:
        raise MarketDataQueryServiceError("CURSOR_EXPIRY_INVALID")
    if binding.policy_descriptor_hash is None:
        raise MarketDataQueryServiceError("CURSOR_POLICY_UNBOUND")
    binding_digest = _cursor_binding_digest(binding)
    payload = _canonical_cursor_payload(
        {
            "version": _CURSOR_VERSION,
            "query_fingerprint": query_fingerprint,
            "policy_descriptor_hash": binding_digest.policy_descriptor_hash,
            "access_grant_descriptor_hash": binding_digest.access_grant_descriptor_hash,
            "principal_scope_sha256": binding_digest.principal_scope_sha256,
            "tenant_scope_sha256": binding_digest.tenant_scope_sha256,
            "entitlement_revision_sha256": binding_digest.entitlement_revision_sha256,
            "visibility_anchor": _cursor_anchor_payload(visibility_anchor),
            "identity_visibility_anchor": _cursor_anchor_payload(identity_visibility_anchor),
            "event_at": parsed_event_at.isoformat(),
            "revision_id": key[1],
            "issued_at": normalized_issued_at.isoformat(),
            "expires_at": normalized_expires_at.isoformat(),
        }
    )
    signature = hmac.new(signing_key, payload, hashlib.sha256).digest()
    token = f"{_base64url_encode(payload)}.{_base64url_encode(signature)}"
    if len(token) > _MAX_CURSOR_TOKEN_LENGTH:
        raise MarketDataQueryServiceError("CURSOR_PAYLOAD_TOO_LARGE")
    return token


def _decode_cursor(
    cursor: str,
    *,
    signing_key: bytes,
    now: datetime,
    expected_binding: MarketDataCursorBinding | None = None,
    query_fingerprint: str | None = None,
) -> _Cursor:
    try:
        encoded_payload, encoded_signature = _split_cursor_token(cursor)
        decoded = _base64url_decode(encoded_payload)
        signature = _base64url_decode(encoded_signature)
        if len(decoded) > _MAX_CURSOR_PAYLOAD_BYTES or len(signature) != _CURSOR_HMAC_DIGEST_BYTES:
            raise ValueError("invalid cursor segment length")
        expected_signature = hmac.new(signing_key, decoded, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_signature, signature):
            raise MarketDataQueryServiceError("CURSOR_SIGNATURE_INVALID")
        payload = _cursor_object_mapping(
            json.loads(decoded.decode("utf-8")),
            field_name="cursor payload",
        )
    except MarketDataQueryServiceError:
        raise
    except (
        UnicodeEncodeError,
        UnicodeDecodeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise MarketDataQueryServiceError("CURSOR_INVALID") from exc
    if set(payload) != {
        "version",
        "query_fingerprint",
        "policy_descriptor_hash",
        "access_grant_descriptor_hash",
        "principal_scope_sha256",
        "tenant_scope_sha256",
        "entitlement_revision_sha256",
        "visibility_anchor",
        "identity_visibility_anchor",
        "event_at",
        "revision_id",
        "issued_at",
        "expires_at",
    }:
        raise MarketDataQueryServiceError("CURSOR_INVALID")
    if payload.get("version") != _CURSOR_VERSION:
        raise MarketDataQueryServiceError("CURSOR_VERSION_UNSUPPORTED")
    fingerprint = payload.get("query_fingerprint")
    event_at = payload.get("event_at")
    revision_id = payload.get("revision_id")
    if (
        not isinstance(fingerprint, str)
        or not isinstance(event_at, str)
        or not isinstance(revision_id, str)
    ):
        raise MarketDataQueryServiceError("CURSOR_INVALID")
    try:
        _require_sha256(fingerprint, field_name="cursor query fingerprint")
        principal_scope_sha256 = _require_sha256(
            payload.get("principal_scope_sha256"),
            field_name="cursor principal scope hash",
        )
        tenant_scope_sha256 = _require_sha256(
            payload.get("tenant_scope_sha256"),
            field_name="cursor tenant scope hash",
        )
        entitlement_revision_sha256 = _require_sha256(
            payload.get("entitlement_revision_sha256"),
            field_name="cursor entitlement revision hash",
        )
        policy_descriptor_hash = _require_sha256(
            payload.get("policy_descriptor_hash"),
            field_name="cursor policy descriptor hash",
        )
        access_grant_descriptor_hash_value = payload.get("access_grant_descriptor_hash")
        access_grant_descriptor_hash = (
            _require_sha256(
                access_grant_descriptor_hash_value,
                field_name="cursor access grant descriptor hash",
            )
            if access_grant_descriptor_hash_value is not None
            else None
        )
        binding = _CursorBindingDigest(
            principal_scope_sha256=principal_scope_sha256,
            tenant_scope_sha256=tenant_scope_sha256,
            entitlement_revision_sha256=entitlement_revision_sha256,
            policy_descriptor_hash=policy_descriptor_hash,
            access_grant_descriptor_hash=access_grant_descriptor_hash,
        )
        visibility_anchor = _decode_cursor_anchor(
            payload.get("visibility_anchor"),
            field_name="cursor visibility_anchor",
        )
        identity_visibility_anchor = _decode_cursor_anchor(
            payload.get("identity_visibility_anchor"),
            field_name="cursor identity_visibility_anchor",
        )
        parsed_event = _parse_cursor_datetime(event_at, field_name="cursor event_at")
        parsed_issued_at = _parse_cursor_datetime(
            payload.get("issued_at"),
            field_name="cursor issued_at",
        )
        parsed_expires_at = _parse_cursor_datetime(
            payload.get("expires_at"),
            field_name="cursor expires_at",
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataQueryServiceError("CURSOR_INVALID") from exc
    if parsed_expires_at <= parsed_issued_at:
        raise MarketDataQueryServiceError("CURSOR_INVALID")
    try:
        normalized_now = _normalize_cursor_datetime(now, field_name="cursor verification time")
    except (TypeError, ValueError) as exc:
        raise MarketDataQueryServiceError("CURSOR_INVALID") from exc
    if normalized_now >= parsed_expires_at:
        raise MarketDataQueryServiceError("CURSOR_EXPIRED")
    if query_fingerprint is not None and fingerprint != query_fingerprint:
        raise MarketDataQueryServiceError("CURSOR_QUERY_MISMATCH")
    if expected_binding is not None:
        _assert_cursor_binding_matches(binding, expected_binding)
    try:
        normalized_revision_id = _require_text(
            revision_id,
            field_name="cursor revision_id",
            maximum=255,
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataQueryServiceError("CURSOR_INVALID") from exc
    return _Cursor(
        query_fingerprint=fingerprint,
        key=(parsed_event.isoformat(), normalized_revision_id),
        visibility_anchor=visibility_anchor,
        identity_visibility_anchor=identity_visibility_anchor,
        binding=binding,
        issued_at=parsed_issued_at,
        expires_at=parsed_expires_at,
    )


def _cursor_anchor_payload(anchor: MarketDataVisibilityAnchor) -> dict[str, object]:
    return {
        "visible_at": anchor.visible_at.isoformat(),
        "max_visibility_sequence": anchor.max_visibility_sequence,
    }


def _decode_cursor_anchor(value: object, *, field_name: str) -> MarketDataVisibilityAnchor:
    anchor_payload = _cursor_object_mapping(value, field_name=field_name)
    if set(anchor_payload) != {
        "visible_at",
        "max_visibility_sequence",
    }:
        raise ValueError(f"{field_name} must have the complete anchor shape")
    max_visibility_sequence = anchor_payload.get("max_visibility_sequence")
    if (
        not isinstance(max_visibility_sequence, int)
        or isinstance(max_visibility_sequence, bool)
        or max_visibility_sequence < 0
    ):
        raise ValueError(f"{field_name} max_visibility_sequence must be a non-negative integer")
    return MarketDataVisibilityAnchor(
        visible_at=_parse_cursor_datetime(
            anchor_payload.get("visible_at"), field_name=f"{field_name} visible_at"
        ),
        max_visibility_sequence=max_visibility_sequence,
    )


def _cursor_object_mapping(value: object, *, field_name: str) -> dict[str, object]:
    """Narrow JSON objects to string keys and object values before field access."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        normalized_item: object = item
        normalized[key] = normalized_item
    return normalized


def _assert_cursor_binding_matches(
    cursor_binding: _CursorBindingDigest,
    expected_binding: MarketDataCursorBinding,
) -> None:
    """Reject a token replayed under a different authenticated access context."""
    expected = _cursor_binding_digest(expected_binding)
    if cursor_binding.principal_scope_sha256 != expected.principal_scope_sha256:
        raise MarketDataQueryServiceError("CURSOR_PRINCIPAL_MISMATCH")
    if cursor_binding.tenant_scope_sha256 != expected.tenant_scope_sha256:
        raise MarketDataQueryServiceError("CURSOR_TENANT_MISMATCH")
    if cursor_binding.entitlement_revision_sha256 != expected.entitlement_revision_sha256:
        raise MarketDataQueryServiceError("CURSOR_ENTITLEMENT_MISMATCH")
    if cursor_binding.policy_descriptor_hash != expected.policy_descriptor_hash:
        raise MarketDataQueryServiceError("CURSOR_POLICY_MISMATCH")
    if (
        expected.access_grant_descriptor_hash is not None
        and cursor_binding.access_grant_descriptor_hash != expected.access_grant_descriptor_hash
    ):
        raise MarketDataQueryServiceError("CURSOR_ACCESS_GRANT_MISMATCH")


def _assert_cursor_access_grant_matches(
    cursor_binding: _CursorBindingDigest,
    expected_binding: MarketDataCursorBinding,
) -> None:
    """Recheck the source decision once identity/context becomes available."""
    expected_hash = expected_binding.access_grant_descriptor_hash
    if expected_hash is None:
        raise MarketDataQueryServiceError("CURSOR_ACCESS_GRANT_UNBOUND")
    if cursor_binding.access_grant_descriptor_hash != expected_hash:
        raise MarketDataQueryServiceError("CURSOR_ACCESS_GRANT_MISMATCH")


def _cursor_binding_digest(binding: MarketDataCursorBinding) -> _CursorBindingDigest:
    """Hash every caller-supplied access dimension with a field domain tag."""
    if binding.policy_descriptor_hash is None:
        raise MarketDataQueryServiceError("CURSOR_POLICY_UNBOUND")
    return _CursorBindingDigest(
        principal_scope_sha256=_cursor_binding_value_hash(
            "principal_scope",
            binding.principal_scope,
        ),
        tenant_scope_sha256=_cursor_binding_value_hash(
            "tenant_scope",
            binding.tenant_scope,
        ),
        entitlement_revision_sha256=_cursor_binding_value_hash(
            "entitlement_revision",
            binding.entitlement_revision,
        ),
        policy_descriptor_hash=binding.policy_descriptor_hash,
        access_grant_descriptor_hash=binding.access_grant_descriptor_hash,
    )


def _cursor_binding_value_hash(field_name: str, value: str) -> str:
    """Return a non-secret fixed-size digest for one cursor access field."""
    normalized_name = _require_text(field_name, field_name="cursor binding field", maximum=64)
    normalized_value = _require_text(value, field_name=f"cursor {normalized_name}", maximum=256)
    return hashlib.sha256(
        b"market-data-cursor-access-binding-v1\x00"
        + normalized_name.encode("utf-8")
        + b"\x00"
        + normalized_value.encode("utf-8")
    ).hexdigest()


def _canonical_cursor_payload(value: Mapping[str, object]) -> bytes:
    """Encode one bounded deterministic HMAC message without JSON whitespace."""
    payload = _canonical_json_bytes(value)
    if len(payload) > _MAX_CURSOR_PAYLOAD_BYTES:
        raise MarketDataQueryServiceError("CURSOR_PAYLOAD_TOO_LARGE")
    return payload


def _canonical_json_bytes(value: object) -> bytes:
    """Canonicalize hash inputs independently from cursor transport limits."""
    try:
        return json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MarketDataQueryServiceError("CURSOR_CANONICALIZATION_INVALID") from exc


def _normalize_cursor_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_cursor_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    return _normalize_cursor_datetime(parsed, field_name=field_name)


def _coerce_cursor_signing_key(value: str | bytes) -> bytes:
    """Validate an operator-supplied cursor HMAC key without logging it."""
    if isinstance(value, str):
        key = value.encode("utf-8")
    elif isinstance(value, bytes):
        key = value
    else:
        raise MarketDataQueryServiceError("CURSOR_SIGNING_KEY_INVALID")
    if not key:
        raise MarketDataQueryServiceError("CURSOR_SIGNING_KEY_UNAVAILABLE")
    if len(key) < 32:
        raise MarketDataQueryServiceError("CURSOR_SIGNING_KEY_INVALID")
    return key


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    if not value or any(character not in _BASE64URL_CHARACTERS for character in value):
        raise ValueError("invalid base64url segment")
    decoded = base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))
    if _base64url_encode(decoded) != value:
        raise ValueError("non-canonical base64url segment")
    return decoded


def _split_cursor_token(cursor: str) -> tuple[str, str]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > _MAX_CURSOR_TOKEN_LENGTH:
        raise ValueError("invalid cursor token")
    parts = cursor.split(".")
    if len(parts) != 2:
        raise ValueError("invalid cursor token")
    return parts[0], parts[1]


def _require_text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must be non-empty and no longer than {maximum} characters")
    return normalized


def _require_sha256(value: object, *, field_name: str) -> str:
    normalized = _require_text(value, field_name=field_name, maximum=64)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized
