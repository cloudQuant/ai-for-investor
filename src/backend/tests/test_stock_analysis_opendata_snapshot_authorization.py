"""Pure-policy tests for scoped OpenData snapshot authorization."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.stock_analysis.opendata_snapshot_authorization import (
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

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 4, 0, tzinfo=UTC)
SCOPE = StockAnalysisSnapshotScope(
    user_id="user-1",
    dataset_id="sina_lrb_report_observations",
    source_id="sina-lrb",
    instrument_id="600519.SH",
    market="SH",
    publication_id="a" * 32,
    capture_id="b" * 64,
)
PRINCIPAL = CurrentPrincipalEvidence(
    user_id="user-1",
    is_active=True,
    permissions=frozenset({"data:read"}),
    entitlement_revision="entitlement-3",
)
USER_GRANT = UserReadDataGrantEvidence(
    grant_id="user-grant-1",
    revision=4,
    revocation_revision=1,
    permission="data:read",
    user_id="user-1",
    dataset_id="sina_lrb_report_observations",
    instrument_id="600519.SH",
    market="SH",
    publication_id="a" * 32,
    capture_id="b" * 64,
    purpose="RESEARCH",
    valid_from=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=2),
    revoked_at=None,
)
SOURCE_GRANT = SourceResearchGrantEvidence(
    grant_id="source-grant-1",
    revision=7,
    revocation_revision=2,
    source_registry_revision="registry-12",
    user_id="user-1",
    source_id="sina-lrb",
    dataset_id="sina_lrb_report_observations",
    instrument_id="600519.SH",
    market="SH",
    publication_id="a" * 32,
    capture_id="b" * 64,
    purpose="RESEARCH",
    valid_from=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
    revoked_at=None,
)
SOURCE_REGISTRY = CurrentSourceRegistryEvidence(
    principal_user_id="user-1",
    entitlement_revision="entitlement-3",
    source_id="sina-lrb",
    dataset_id="sina_lrb_report_observations",
    market="SH",
    purpose="RESEARCH",
    revision="registry-12",
    research_allowed=True,
)


def _authorize(
    *,
    scope: StockAnalysisSnapshotScope = SCOPE,
    principal: CurrentPrincipalEvidence | None = PRINCIPAL,
    user_grant: UserReadDataGrantEvidence | None = USER_GRANT,
    source_grant: SourceResearchGrantEvidence | None = SOURCE_GRANT,
    source_registry: CurrentSourceRegistryEvidence | None = SOURCE_REGISTRY,
    now: datetime = NOW,
) -> StockAnalysisSnapshotAuthorizationReceipt:
    return authorize_stock_analysis_snapshot(
        scope=scope,
        principal=principal,
        user_grant=user_grant,
        source_grant=source_grant,
        source_registry=source_registry,
        now=now,
    )


def _revalidate(
    receipt: StockAnalysisSnapshotAuthorizationReceipt | None,
    *,
    scope: StockAnalysisSnapshotScope = SCOPE,
    principal: CurrentPrincipalEvidence | None = PRINCIPAL,
    user_grant: UserReadDataGrantEvidence | None = USER_GRANT,
    source_grant: SourceResearchGrantEvidence | None = SOURCE_GRANT,
    source_registry: CurrentSourceRegistryEvidence | None = SOURCE_REGISTRY,
    now: datetime = NOW + timedelta(minutes=1),
) -> StockAnalysisSnapshotAuthorizationReceipt:
    return revalidate_stock_analysis_snapshot(
        scope=scope,
        receipt=receipt,
        principal=principal,
        user_grant=user_grant,
        source_grant=source_grant,
        source_registry=source_registry,
        now=now,
    )


def _assert_denied(code: str, **overrides: object) -> None:
    arguments: dict[str, object] = {
        "scope": SCOPE,
        "principal": PRINCIPAL,
        "user_grant": USER_GRANT,
        "source_grant": SOURCE_GRANT,
        "source_registry": SOURCE_REGISTRY,
        "now": NOW,
    }
    arguments.update(overrides)
    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        authorize_stock_analysis_snapshot(**arguments)  # type: ignore[arg-type]
    assert error.value.code == code


def test_exact_current_scope_returns_a_non_secret_versioned_receipt() -> None:
    receipt = _authorize()

    assert receipt.scope_sha256
    assert receipt.receipt_version == "stock-analysis-opendata-access-v1"
    assert receipt.user_grant_id == USER_GRANT.grant_id
    assert receipt.user_grant_revision == USER_GRANT.revision
    assert receipt.source_grant_id == SOURCE_GRANT.grant_id
    assert receipt.source_grant_revision == SOURCE_GRANT.revision
    assert receipt.source_registry_revision == SOURCE_REGISTRY.revision
    assert receipt.expires_at == SOURCE_GRANT.expires_at
    assert receipt.decision_sha256


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("user_id", "other-user", "principal_read_data_denied"),
        ("is_active", False, "principal_read_data_denied"),
        ("permissions", frozenset(), "principal_read_data_denied"),
        ("entitlement_revision", "", "principal_read_data_denied"),
    ],
)
def test_current_principal_must_be_active_and_have_read_data(
    field: str, value: object, code: str
) -> None:
    _assert_denied(code, principal=replace(PRINCIPAL, **{field: value}))


@pytest.mark.parametrize(
    "field",
    [
        "user_id",
        "dataset_id",
        "instrument_id",
        "market",
        "publication_id",
        "capture_id",
        "purpose",
    ],
)
def test_user_read_grant_must_match_each_exact_scope_field(field: str) -> None:
    value = getattr(USER_GRANT, field)
    replacement = "other" if value != "other" else "changed"
    _assert_denied(
        "user_grant_scope_mismatch",
        user_grant=replace(USER_GRANT, **{field: replacement}),
    )


def test_user_read_grant_requires_the_exact_read_data_permission() -> None:
    _assert_denied(
        "user_grant_scope_mismatch",
        user_grant=replace(USER_GRANT, permission="data:upload"),
    )


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("user_id", "source_grant_scope_mismatch"),
        ("source_id", "source_grant_scope_mismatch"),
        ("dataset_id", "source_grant_scope_mismatch"),
        ("instrument_id", "source_grant_scope_mismatch"),
        ("market", "source_grant_scope_mismatch"),
        ("publication_id", "source_grant_scope_mismatch"),
        ("capture_id", "source_grant_scope_mismatch"),
        ("purpose", "source_grant_scope_mismatch"),
        ("source_registry_revision", "source_registry_revision_mismatch"),
    ],
)
def test_source_grant_must_match_current_source_scope_and_registry_revision(
    field: str, code: str
) -> None:
    value = getattr(SOURCE_GRANT, field)
    replacement = "other" if value != "other" else "changed"
    _assert_denied(
        code,
        source_grant=replace(SOURCE_GRANT, **{field: replacement}),
    )


@pytest.mark.parametrize(
    ("grant_name", "revoked_code"),
    [
        ("user_grant", "user_grant_revoked"),
        ("source_grant", "source_grant_revoked"),
    ],
)
def test_any_revoked_grant_denies(grant_name: str, revoked_code: str) -> None:
    grant = USER_GRANT if grant_name == "user_grant" else SOURCE_GRANT
    revoked = replace(grant, revoked_at=NOW - timedelta(seconds=1))
    _assert_denied(revoked_code, **{grant_name: revoked})


@pytest.mark.parametrize(
    ("grant_name", "edge"),
    [
        ("user_grant", "before"),
        ("user_grant", "expiry"),
        ("source_grant", "before"),
        ("source_grant", "expiry"),
    ],
)
def test_grant_validity_window_is_start_inclusive_and_expiry_exclusive(
    grant_name: str, edge: str
) -> None:
    grant = USER_GRANT if grant_name == "user_grant" else SOURCE_GRANT
    timestamp = (
        grant.valid_from - timedelta(microseconds=1) if edge == "before" else grant.expires_at
    )
    _assert_denied(
        "authorization_expired",
        **{grant_name: grant},
        now=timestamp,
    )


@pytest.mark.parametrize(
    "scope",
    [
        replace(SCOPE, dataset_id="unknown_dataset"),
        replace(SCOPE, dataset_id="sina_fzb_report_observations"),
        replace(SCOPE, instrument_id="000001.BJ", market="BJ"),
        replace(SCOPE, market="SZ"),
        replace(SCOPE, publication_id="not-a-publication"),
        replace(SCOPE, capture_id="not-a-capture"),
        replace(SCOPE, purpose="DISPLAY"),
    ],
)
def test_unsupported_or_malformed_scope_is_rejected(scope: StockAnalysisSnapshotScope) -> None:
    _assert_denied("authorization_scope_invalid", scope=scope)


@pytest.mark.parametrize(
    ("principal", "user_grant", "source_grant"),
    [
        (None, USER_GRANT, SOURCE_GRANT),
        (PRINCIPAL, None, SOURCE_GRANT),
        (PRINCIPAL, USER_GRANT, None),
    ],
)
def test_missing_authority_evidence_defaults_to_deny(
    principal: CurrentPrincipalEvidence | None,
    user_grant: UserReadDataGrantEvidence | None,
    source_grant: SourceResearchGrantEvidence | None,
) -> None:
    _assert_denied(
        "authorization_evidence_missing",
        principal=principal,
        user_grant=user_grant,
        source_grant=source_grant,
    )


def test_naive_evaluation_clock_is_rejected() -> None:
    _assert_denied("authorization_clock_invalid", now=NOW.replace(tzinfo=None))


def test_current_registry_decision_must_be_independently_present() -> None:
    _assert_denied("source_registry_evidence_missing", source_registry=None)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("principal_user_id", "other-user", "source_registry_scope_mismatch"),
        ("entitlement_revision", "entitlement-4", "source_registry_scope_mismatch"),
        ("source_id", "other-source", "source_registry_scope_mismatch"),
        ("dataset_id", "other-dataset", "source_registry_scope_mismatch"),
        ("market", "SZ", "source_registry_scope_mismatch"),
        ("purpose", "DISPLAY", "source_registry_scope_mismatch"),
        ("revision", "", "source_registry_scope_mismatch"),
        ("research_allowed", False, "source_registry_research_denied"),
    ],
)
def test_current_registry_evidence_must_match_and_allow_research(
    field: str, value: object, code: str
) -> None:
    _assert_denied(
        code,
        source_registry=replace(SOURCE_REGISTRY, **{field: value}),
    )


def test_current_registry_revision_is_compared_with_the_grant_claim() -> None:
    _assert_denied(
        "source_registry_revision_mismatch",
        source_registry=replace(SOURCE_REGISTRY, revision="registry-13"),
    )


@pytest.mark.parametrize("grant_name", ["user_grant", "source_grant"])
def test_grant_valid_from_is_inclusive(grant_name: str) -> None:
    grant = USER_GRANT if grant_name == "user_grant" else SOURCE_GRANT

    receipt = _authorize(**{grant_name: grant}, now=grant.valid_from)

    assert receipt.authorized_at == grant.valid_from


def test_revalidation_accepts_same_current_versions_before_expiry() -> None:
    receipt = _authorize()

    assert _revalidate(receipt) is receipt


def test_revalidation_requires_the_creation_receipt() -> None:
    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(None)

    assert error.value.code == "authorization_receipt_missing"


def test_revalidation_rejects_changed_instrument_or_publication() -> None:
    receipt = _authorize()
    changed_scope = replace(SCOPE, publication_id="c" * 32)

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(receipt, scope=changed_scope)

    assert error.value.code == "authorization_scope_changed"


@pytest.mark.parametrize(
    ("principal", "user_grant", "source_grant", "code"),
    [
        (
            replace(PRINCIPAL, entitlement_revision="entitlement-4"),
            USER_GRANT,
            SOURCE_GRANT,
            "source_registry_scope_mismatch",
        ),
        (
            PRINCIPAL,
            replace(USER_GRANT, revision=5),
            SOURCE_GRANT,
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            replace(USER_GRANT, revocation_revision=2),
            SOURCE_GRANT,
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            replace(USER_GRANT, valid_from=USER_GRANT.valid_from + timedelta(minutes=1)),
            SOURCE_GRANT,
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            USER_GRANT,
            replace(SOURCE_GRANT, revision=8),
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            USER_GRANT,
            replace(SOURCE_GRANT, revocation_revision=3),
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            USER_GRANT,
            replace(SOURCE_GRANT, expires_at=SOURCE_GRANT.expires_at + timedelta(minutes=1)),
            "authorization_revision_changed",
        ),
        (
            PRINCIPAL,
            USER_GRANT,
            replace(SOURCE_GRANT, source_registry_revision="registry-13"),
            "source_registry_revision_mismatch",
        ),
    ],
)
def test_revalidation_rejects_changed_entitlement_or_grant_version(
    principal: CurrentPrincipalEvidence,
    user_grant: UserReadDataGrantEvidence,
    source_grant: SourceResearchGrantEvidence,
    code: str,
) -> None:
    receipt = _authorize()

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(receipt, principal=principal, user_grant=user_grant, source_grant=source_grant)

    assert error.value.code == code


def test_revalidation_rejects_expired_authorization() -> None:
    receipt = _authorize()

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(receipt, now=receipt.expires_at)

    assert error.value.code == "authorization_expired"


def test_revalidation_rejects_mutated_receipt_digest() -> None:
    receipt = _authorize()
    forged = replace(receipt, authorized_at=receipt.authorized_at + timedelta(seconds=1))

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(forged)

    assert error.value.code == "authorization_receipt_invalid"


def test_revalidation_rejects_corrupt_receipt_digest() -> None:
    receipt = _authorize()
    forged = replace(receipt, decision_sha256="0" * 64)

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(forged)

    assert error.value.code == "authorization_receipt_invalid"


def test_receipt_version_is_explicit_and_must_be_supported() -> None:
    receipt = _authorize()
    unknown_version = replace(receipt, receipt_version="stock-analysis-opendata-access-v2")

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(unknown_version)

    assert error.value.code == "authorization_receipt_invalid"


def test_receipt_cannot_predate_the_later_grant_valid_from() -> None:
    later_source_grant = replace(
        SOURCE_GRANT,
        valid_from=NOW - timedelta(minutes=30),
    )
    receipt = _authorize(source_grant=later_source_grant)
    before_later_grant = replace(
        receipt,
        authorized_at=NOW - timedelta(minutes=45),
    )

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(before_later_grant)

    assert error.value.code == "authorization_receipt_invalid"


def test_revalidation_detects_current_registry_change_independently_of_grant_revision() -> None:
    receipt = _authorize()
    current_source_grant = replace(SOURCE_GRANT, source_registry_revision="registry-13")
    current_registry = replace(SOURCE_REGISTRY, revision="registry-13")

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(
            receipt,
            source_grant=current_source_grant,
            source_registry=current_registry,
        )

    assert error.value.code == "authorization_revision_changed"


def test_revalidation_rejects_receipt_claimed_from_the_future() -> None:
    receipt = _authorize()
    future_receipt = replace(receipt, authorized_at=NOW + timedelta(minutes=2))

    with pytest.raises(StockAnalysisSnapshotAuthorizationError) as error:
        _revalidate(future_receipt)

    assert error.value.code == "authorization_receipt_invalid"
