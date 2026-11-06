"""Durable attestation writing for the market-data capability ledger.

These tests pin the two properties the acceptance plan cares about: an
attestation records what it actually means, and a ``verified`` or
``authorized`` claim cannot be minted without durable receipts the checker can
re-read.  Caller-supplied descriptor or evidence hashes are not accepted by any
surface exercised here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.data.capability_ledger_admin import get_reviewed_market_data_source_policy
from app.db.database import async_session_maker
from app.main import app
from app.models.audit_record import AuditRecord
from app.models.data_governance import DgDataset, DgProvider
from app.models.market_data_platform import (
    SOURCE_AUTHORIZATION_STATE_VERIFIED,
    ImmutableMarketDataRecordError,
    MdCapabilityLedgerEntry,
    MdDataSeries,
    MdObservationRevision,
    MdPublication,
    MdSourceSnapshot,
)
from app.models.permission import Role, user_roles
from app.models.user import User
from app.schemas.market_data_capability_ledger import MarketDataCapabilityLedgerRecordRequest
from app.services.market_data.capability_ledger import (
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MarketDataCapabilityEvaluation,
    MarketDataCapabilityLedger,
    rollout_capability_descriptor_sha256,
    route_capability_descriptor_sha256,
    route_capability_id,
)
from app.services.market_data.capability_ledger_admin import (
    CapabilityLedgerAdminError,
    MarketDataCapabilityLedgerAdminService,
)
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
    MarketDataSourcePolicyRegistry,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
POLICY_ID = "market-default-v1"
PROVIDER_ID = "ledger-akshare"
ROUTE_ID = "ledger-stock-primary-v1"
SECOND_ROUTE_ID = "ledger-fund-primary-v1"
ACTOR_ID = "ledger-operator"
LEDGER_ROUTE_PATH = "/api/v1/data/market-data/capability-ledger/records"


def _digest(index: int) -> str:
    return format(index * 17 + 7, "064x")


class _NoNetworkProvider:
    async def fetch(self, _request: object) -> object:
        raise AssertionError("capability ledger admin tests must not call providers")


def _settings(**overrides: bool) -> SimpleNamespace:
    values: dict[str, object] = {
        "MARKET_DATA_QUERY_V2_ENABLED": True,
        "MARKET_DATA_ONLINE_FETCH_ENABLED": True,
        "MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED": True,
        "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _route(route_id: str = ROUTE_ID, *, asset_type: str = "stock") -> MarketDataProviderRoute:
    return MarketDataProviderRoute(
        route_id=route_id,
        request_provider=PROVIDER_ID,
        expected_result_provider_ids=frozenset({PROVIDER_ID}),
        asset_types=frozenset({asset_type}),
        data_kinds=frozenset({"bars"}),
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE"}),
        adjustments=frozenset({"qfq"}),
        price_bases=frozenset({"close"}),
        currencies=frozenset({"CNY"}),
        units=frozenset({"share"}),
        adapter=_NoNetworkProvider(),
    )


def _policy(*routes: MarketDataProviderRoute) -> MarketDataSourcePolicy:
    return MarketDataSourcePolicy(
        policy_id=POLICY_ID,
        allowed_purposes=frozenset({"display", "research"}),
        routes=routes or (_route(),),
    )


def _resolved_query(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source_policy_id": POLICY_ID,
        "data_kind": "bars",
        "frequency": "1d",
        "adjustment": "qfq",
        "price_basis": "close",
        "currency": "CNY",
        "unit": "share",
        "family_id": None,
        "family_contract_version": None,
        "identity": {"asset_type": "stock", "market": "CN-SSE", "symbol": "600000"},
    }
    base.update(overrides)
    return base


async def _seed_durable_receipt(
    *,
    ordinal: int = 1,
    route: MarketDataProviderRoute | None = None,
    base_time: datetime = NOW,
    verified_state: str | None = SOURCE_AUTHORIZATION_STATE_VERIFIED,
    seal_mismatch: bool = False,
    with_series: bool = True,
    resolved_query: Mapping[str, Any] | None = None,
) -> str:
    """Persist one complete verified fetch chain and return its snapshot ID."""
    effective_route = route or _route()
    retrieved_at = base_time - timedelta(hours=3)
    payload_sha256 = _digest(ordinal)
    async with async_session_maker() as session:
        provider = await session.scalar(
            select(DgProvider).where(DgProvider.provider_id == PROVIDER_ID)
        )
        if provider is None:
            provider = DgProvider(
                provider_id=PROVIDER_ID,
                name="Ledger test source",
                category="market",
                is_active=True,
            )
            session.add(provider)
            await session.flush()
        dataset = DgDataset(
            dataset_code=f"ledger.test_{ordinal}",
            display_name="Ledger test dataset",
            domain="market",
            canonical_schema={},
            primary_key=[],
            is_active=True,
        )
        session.add(dataset)
        await session.flush()

        snapshot = MdSourceSnapshot(
            provider_id=str(provider.id),
            platform="akshare",
            source_id=PROVIDER_ID,
            adapter_id="ledger-adapter",
            endpoint_version="test-v1",
            request_fingerprint_sha256=_digest(100 + ordinal),
            provider_request_id=f"ledger-provider-request-{ordinal:032d}",
            provider_request_fingerprint_sha256=_digest(200 + ordinal),
            query_fingerprint_sha256=_digest(300 + ordinal),
            source_authorization_state=verified_state,
            source_authorization_descriptor_sha256=(
                _digest(400 + ordinal)
                if verified_state == SOURCE_AUTHORIZATION_STATE_VERIFIED
                else None
            ),
            payload_sha256=payload_sha256,
            request_json={
                "resolved_query": dict(
                    resolved_query
                    if resolved_query is not None
                    else _resolved_query(
                        family_id=effective_route.family_id,
                        family_contract_version=effective_route.family_contract_version,
                    )
                )
            },
            payload_manifest_json={},
            provenance_json={},
            retrieved_at=retrieved_at,
        )
        session.add(snapshot)
        await session.flush()

        session.add(
            MdPublication(
                entity_type="source_snapshot",
                entity_id=snapshot.id,
                entity_sha256=_digest(800 + ordinal) if seal_mismatch else payload_sha256,
                published_at=retrieved_at + timedelta(minutes=1),
                visibility_sequence=ordinal,
            )
        )
        if with_series:
            series = MdDataSeries(
                dataset_id=str(dataset.id),
                canonical_id=f"instrument:stock:CN-SSE:600{ordinal:03d}",
                data_kind="bars",
                frequency="1d",
                semantic_key_sha256=_digest(500 + ordinal),
                semantic_identity_json={"asset_type": "stock", "market": "CN-SSE"},
            )
            session.add(series)
            await session.flush()
            session.add(
                MdObservationRevision(
                    series_id=str(series.id),
                    event_time=retrieved_at,
                    available_at=retrieved_at + timedelta(minutes=1),
                    source_snapshot_id=str(snapshot.id),
                    quality_status="PASS",
                    quality_policy_version="test-v1",
                    quality_details_json={},
                    fields_json={"close": 1.0},
                    fields_sha256=_digest(600 + ordinal),
                    revision_number=1,
                    revision_key_sha256=_digest(700 + ordinal),
                    normalization_version="test-v1",
                    provenance_json={},
                    committed_at=retrieved_at + timedelta(minutes=1),
                )
            )
        await session.commit()
        return str(snapshot.id)


async def _ensure_operator(actor_user_id: str = ACTOR_ID, *, is_active: bool = True) -> None:
    async with async_session_maker() as session:
        if await session.scalar(select(User).where(User.id == actor_user_id)) is not None:
            return
        session.add(
            User(
                id=actor_user_id,
                username=f"ledger-{actor_user_id.replace('-', '_')}",
                email=f"{actor_user_id}@ledger.test",
                hashed_password="x" * 64,
                is_active=is_active,
                principal_kind="HUMAN",
            )
        )
        await session.commit()


async def _append(
    policy: MarketDataSourcePolicy,
    *,
    capability_id: str = MARKET_DATA_QUERY_V2_CAPABILITY,
    stage: str,
    effective_from: datetime,
    effective_until: datetime,
    verified_until: datetime | None = None,
    authorized_until: datetime | None = None,
    actor_user_id: str = ACTOR_ID,
) -> Any:
    if actor_user_id == ACTOR_ID:
        await _ensure_operator(ACTOR_ID)
    async with async_session_maker() as session:
        service = MarketDataCapabilityLedgerAdminService(session, clock=lambda: NOW)
        return await service.append_record(
            capability_id=capability_id,
            stage=stage,  # type: ignore[arg-type]
            policy=policy,
            actor_user_id=actor_user_id,
            effective_from=effective_from,
            effective_until=effective_until,
            verified_until=verified_until,
            authorized_until=authorized_until,
        )


async def _evaluate(
    policy: MarketDataSourcePolicy,
    *,
    settings: object | None = None,
    now: datetime = NOW,
) -> MarketDataCapabilityEvaluation:
    async with async_session_maker() as session:
        return await MarketDataCapabilityLedger(session, clock=lambda: now).evaluate(
            settings=settings or _settings(),
            source_policies=MarketDataSourcePolicyRegistry((policy,)),
        )


def _state(evaluation: MarketDataCapabilityEvaluation, capability_id: str) -> Any:
    return next(
        state
        for state in evaluation.response.capability_states
        if state.capability_id == capability_id
    )


async def _lifecycle_through(
    policy: MarketDataSourcePolicy,
    *,
    capability_id: str = MARKET_DATA_QUERY_V2_CAPABILITY,
    until_stage: str,
    activation_end: datetime = NOW + timedelta(hours=2),
    base_time: datetime = NOW,
) -> Any:
    """Append the requested prefix of declare -> install -> verify -> authorize.

    Each revision restates the full lifecycle so far, so the newest current
    record is the one the durable reader evaluates.
    """
    stages = ["declared", "installed", "verified", "authorized"]
    wanted = stages[: stages.index(until_stage) + 1]
    total = len(wanted)
    receipt = None
    for index, stage in enumerate(wanted, start=1):
        is_last = index == total
        receipt = await _append(
            policy,
            capability_id=capability_id,
            stage=stage,
            effective_from=base_time + timedelta(hours=index - total - 1),
            effective_until=(
                activation_end if is_last else base_time + timedelta(hours=index - total)
            ),
            verified_until=(base_time + timedelta(hours=6) if stage == "verified" else None),
            authorized_until=(base_time + timedelta(hours=6) if stage == "authorized" else None),
        )
    return receipt


@pytest.mark.asyncio
async def test_declared_only_revision_does_not_enable_query_v2() -> None:
    """A declaration alone is a code fact; the durable gate stays closed."""
    policy = _policy()
    await _lifecycle_through(policy, until_stage="declared")

    evaluation = await _evaluate(policy)
    state = _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY)

    assert evaluation.response.query_v2_enabled is False
    assert state.declared is True
    assert state.installed is False
    assert state.reason_code == "CAPABILITY_NOT_INSTALLED"


@pytest.mark.asyncio
async def test_installed_revision_without_verification_does_not_enable_query_v2() -> None:
    """Installing the runtime is still not evidence that it was verified."""
    policy = _policy()
    await _lifecycle_through(policy, until_stage="installed")

    evaluation = await _evaluate(policy)

    assert evaluation.response.query_v2_enabled is False
    assert _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY).reason_code == (
        "CAPABILITY_NOT_VERIFIED"
    )


@pytest.mark.asyncio
async def test_verified_revision_without_authorization_does_not_enable_query_v2() -> None:
    """Verification alone never grants the capability; authorization is separate."""
    policy = _policy()
    await _seed_durable_receipt()
    await _lifecycle_through(policy, until_stage="verified")

    evaluation = await _evaluate(policy)
    state = _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY)

    assert evaluation.response.query_v2_enabled is False
    assert state.verified is True
    assert state.authorized is False
    assert state.reason_code == "CAPABILITY_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_full_lifecycle_over_durable_receipts_enables_query_v2() -> None:
    """The complete append-only progression is what flips the durable gate."""
    policy = _policy()
    await _seed_durable_receipt()
    receipt = await _lifecycle_through(policy, until_stage="authorized")

    evaluation = await _evaluate(policy)
    state = _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY)

    assert receipt.evidence_kind == "durable-verified-source-receipts-v1"
    assert receipt.artifact_count == 1
    assert evaluation.response.query_v2_enabled is True
    assert state.effective is True
    assert state.reason_code is None
    # A route still needs its own durable attestation; the rollout record alone
    # cannot make a provider route effective.
    assert evaluation.effective_route_ids == frozenset()
    assert _state(evaluation, route_capability_id(ROUTE_ID)).reason_code == (
        "CAPABILITY_LEDGER_MISSING"
    )


@pytest.mark.asyncio
async def test_expired_activation_window_returns_to_disabled() -> None:
    """A lapsed attestation reverts to the ledger-expiry reason, not silence."""
    policy = _policy()
    await _seed_durable_receipt()
    await _lifecycle_through(
        policy,
        until_stage="authorized",
        activation_end=NOW + timedelta(hours=1),
    )

    evaluation = await _evaluate(policy, now=NOW + timedelta(hours=2))

    assert evaluation.response.query_v2_enabled is False
    assert _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY).reason_code == (
        "CAPABILITY_LEDGER_EXPIRED"
    )


@pytest.mark.asyncio
async def test_settings_kill_switch_still_narrows_a_complete_attestation() -> None:
    """Durable evidence cannot override an operator kill switch."""
    policy = _policy()
    await _seed_durable_receipt()
    await _lifecycle_through(policy, until_stage="authorized")

    evaluation = await _evaluate(policy, settings=_settings(MARKET_DATA_QUERY_V2_ENABLED=False))

    assert evaluation.response.query_v2_enabled is False
    assert _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY).reason_code == (
        "CAPABILITY_SETTING_DISABLED"
    )


@pytest.mark.asyncio
async def test_service_refuses_overlapping_activation_window() -> None:
    """Two current records would read AMBIGUOUS, so the writer blocks the shape."""
    policy = _policy()
    await _append(
        policy,
        stage="declared",
        effective_from=NOW - timedelta(hours=1),
        effective_until=NOW + timedelta(hours=1),
    )

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="installed",
            effective_from=NOW,
            effective_until=NOW + timedelta(hours=1),
        )

    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_WINDOW_OVERLAP"
    assert excinfo.value.detail["conflicting_revisions"] == [1]


@pytest.mark.asyncio
async def test_manually_duplicated_current_record_still_reads_ambiguous() -> None:
    """Ambiguity stays reachable and honest for writes that bypass the service."""
    policy = _policy()
    await _append(
        policy,
        stage="declared",
        effective_from=NOW - timedelta(hours=1),
        effective_until=NOW + timedelta(hours=1),
    )
    async with async_session_maker() as session:
        session.add(
            MdCapabilityLedgerEntry(
                capability_id=MARKET_DATA_QUERY_V2_CAPABILITY,
                revision=2,
                descriptor_sha256=rollout_capability_descriptor_sha256(
                    MARKET_DATA_QUERY_V2_CAPABILITY
                ),
                evidence_sha256=_digest(999),
                declared_capability=True,
                effective_from=NOW,
                effective_until=NOW + timedelta(hours=1),
            )
        )
        await session.commit()

    evaluation = await _evaluate(policy)

    assert evaluation.response.query_v2_enabled is False
    assert _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY).reason_code == (
        "CAPABILITY_LEDGER_AMBIGUOUS"
    )


@pytest.mark.asyncio
async def test_verified_stage_without_durable_receipts_is_refused() -> None:
    """No fetched, sealed, normalized receipt means no verification attestation."""
    policy = _policy()
    await _lifecycle_through(
        policy,
        until_stage="installed",
        activation_end=NOW - timedelta(minutes=45),
    )

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="verified",
            effective_from=NOW - timedelta(minutes=30),
            effective_until=NOW + timedelta(hours=1),
            verified_until=NOW + timedelta(hours=1),
        )

    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_EVIDENCE_MISSING"
    async with async_session_maker() as session:
        records = (
            await session.scalars(
                select(MdCapabilityLedgerEntry).where(MdCapabilityLedgerEntry.revision > 2)
            )
        ).all()
    assert records == []


@pytest.mark.parametrize(
    ("verified_state", "with_series", "seal_mismatch", "query_override"),
    [
        (None, True, False, None),
        ("UNVERIFIED_COMPATIBILITY", True, False, None),
        (SOURCE_AUTHORIZATION_STATE_VERIFIED, False, False, None),
        (SOURCE_AUTHORIZATION_STATE_VERIFIED, True, True, None),
        (
            SOURCE_AUTHORIZATION_STATE_VERIFIED,
            True,
            False,
            {"data_kind": "quote_snapshot"},
        ),
        (
            SOURCE_AUTHORIZATION_STATE_VERIFIED,
            True,
            False,
            {"source_policy_id": "other-policy"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_only_fully_attributable_receipts_count_as_evidence(
    verified_state: str | None,
    with_series: bool,
    seal_mismatch: bool,
    query_override: dict[str, Any] | None,
) -> None:
    """Every admissible artifact is verified, sealed, normalized, and on-route."""
    policy = _policy()
    await _seed_durable_receipt(
        verified_state=verified_state,
        with_series=with_series,
        seal_mismatch=seal_mismatch,
        resolved_query=None if query_override is None else _resolved_query(**query_override),
    )
    await _lifecycle_through(
        policy,
        until_stage="installed",
        activation_end=NOW - timedelta(minutes=45),
    )

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="verified",
            effective_from=NOW - timedelta(minutes=30),
            effective_until=NOW + timedelta(hours=1),
            verified_until=NOW + timedelta(hours=1),
        )

    assert excinfo.value.code == (
        "CAPABILITY_LEDGER_ADMIN_EVIDENCE_INTEGRITY"
        if seal_mismatch
        else "CAPABILITY_LEDGER_ADMIN_EVIDENCE_MISSING"
    )


@pytest.mark.asyncio
async def test_rollout_evidence_requires_every_reviewed_route() -> None:
    """A rollout gate cannot be evidenced while a sibling route has no receipts."""
    policy = _policy(_route(), _route(SECOND_ROUTE_ID, asset_type="fund"))
    await _seed_durable_receipt(route=_route())
    await _lifecycle_through(
        policy,
        until_stage="installed",
        activation_end=NOW - timedelta(minutes=45),
    )

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="verified",
            effective_from=NOW - timedelta(minutes=30),
            effective_until=NOW + timedelta(hours=1),
            verified_until=NOW + timedelta(hours=1),
        )

    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_EVIDENCE_MISSING"
    assert excinfo.value.detail["route_id"] == SECOND_ROUTE_ID


@pytest.mark.asyncio
async def test_route_capability_attestation_uses_the_server_derived_descriptor() -> None:
    """A route revision carries the reviewed route's own canonical descriptor."""
    route = _route()
    policy = _policy(route)
    await _seed_durable_receipt(route=route)
    capability_id = route_capability_id(route.route_id)
    # A route is only effective once its rollout dependencies are attested too.
    await _lifecycle_through(policy, until_stage="authorized")
    await _lifecycle_through(
        policy,
        capability_id=MARKET_DATA_ONLINE_FETCH_CAPABILITY,
        until_stage="authorized",
    )

    receipt = await _lifecycle_through(
        policy,
        capability_id=capability_id,
        until_stage="authorized",
    )
    evaluation = await _evaluate(policy)

    assert receipt.descriptor_sha256 == route_capability_descriptor_sha256(route)
    assert evaluation.effective_route_ids == frozenset({route.route_id})

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            capability_id=route_capability_id("never-reviewed-route"),
            stage="declared",
            effective_from=NOW,
            effective_until=NOW + timedelta(hours=1),
        )
    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_ROUTE_UNDECLARED"


@pytest.mark.asyncio
async def test_evidence_digest_is_reproducible_and_flags_descriptor_drift() -> None:
    """Re-derivation from the stored row alone confirms the checkable link."""
    route = _route()
    policy = _policy(route)
    await _seed_durable_receipt(route=route)
    receipt = await _lifecycle_through(policy, until_stage="authorized")

    async with async_session_maker() as session:
        service = MarketDataCapabilityLedgerAdminService(session, clock=lambda: NOW)
        summary = await service.reverify_record(
            capability_id=MARKET_DATA_QUERY_V2_CAPABILITY,
            revision=receipt.revision,
            policy=policy,
        )
        drifted = _policy(replace(route, markets=frozenset({"CN-SZSE"})))
        drift_summary = await service.reverify_record(
            capability_id=MARKET_DATA_QUERY_V2_CAPABILITY,
            revision=receipt.revision,
            policy=drifted,
        )

    assert summary.evidence_sha256 == receipt.evidence_sha256
    assert summary.artifact_count == 1
    assert summary.matches_stored is True
    assert drift_summary.matches_stored is False


@pytest.mark.asyncio
async def test_evidence_digest_ignores_receipts_arriving_after_the_window() -> None:
    """A later fetch cannot silently change what an old attestation meant."""
    policy = _policy()
    await _seed_durable_receipt(ordinal=1)
    receipt = await _lifecycle_through(policy, until_stage="authorized")
    await _seed_durable_receipt(ordinal=2, base_time=NOW + timedelta(days=1))

    async with async_session_maker() as session:
        service = MarketDataCapabilityLedgerAdminService(session, clock=lambda: NOW)
        summary = await service.reverify_record(
            capability_id=MARKET_DATA_QUERY_V2_CAPABILITY,
            revision=receipt.revision,
            policy=policy,
        )

    assert summary.artifact_count == 1
    assert summary.evidence_sha256 == receipt.evidence_sha256


@pytest.mark.asyncio
async def test_append_records_operator_provenance_and_receipt() -> None:
    """Every durable decision is bound to the authenticated operator."""
    policy = _policy()
    receipt = await _append(
        policy,
        stage="declared",
        effective_from=NOW - timedelta(hours=1),
        effective_until=NOW,
    )

    async with async_session_maker() as session:
        audit = (
            await session.scalars(
                select(AuditRecord).where(
                    AuditRecord.event_type == "market_data.capability_ledger.append"
                )
            )
        ).all()

    assert len(audit) == 1
    assert audit[0].user_id == ACTOR_ID
    assert audit[0].event_target == MARKET_DATA_QUERY_V2_CAPABILITY
    payload = json.loads(str(audit[0].event_data))
    assert payload["revision"] == receipt.revision
    assert payload["receipt_sha256"] == receipt.receipt_sha256
    assert payload["evidence_kind"] == "server-owned-descriptor-v1"


@pytest.mark.asyncio
async def test_unknown_operator_is_refused() -> None:
    """An attestation cannot be recorded by an identity the user table lacks."""
    policy = _policy()

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="declared",
            effective_from=NOW - timedelta(hours=1),
            effective_until=NOW,
            actor_user_id="ghost-operator",
        )

    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_ACTOR_UNKNOWN"


@pytest.mark.asyncio
async def test_disabled_operator_is_refused() -> None:
    """An attestation cannot be recorded by a deactivated identity."""
    policy = _policy()
    await _ensure_operator("former-operator", is_active=False)

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="declared",
            effective_from=NOW - timedelta(hours=1),
            effective_until=NOW,
            actor_user_id="former-operator",
        )

    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_ACTOR_DISABLED"


@pytest.mark.asyncio
async def test_lifecycle_ordering_cannot_be_skipped() -> None:
    """Verification cannot be claimed before a declaration and installation."""
    policy = _policy()
    await _seed_durable_receipt()

    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="verified",
            effective_from=NOW - timedelta(hours=1),
            effective_until=NOW,
            verified_until=NOW + timedelta(hours=1),
        )
    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_NOT_DECLARED"

    await _append(
        policy,
        stage="declared",
        effective_from=NOW - timedelta(hours=1),
        effective_until=NOW,
    )
    with pytest.raises(CapabilityLedgerAdminError) as excinfo:
        await _append(
            policy,
            stage="authorized",
            effective_from=NOW,
            effective_until=NOW + timedelta(hours=1),
            authorized_until=NOW + timedelta(hours=1),
        )
    assert excinfo.value.code == "CAPABILITY_LEDGER_ADMIN_NOT_INSTALLED"


@pytest.mark.asyncio
async def test_retired_revision_returns_the_capability_to_undeclared() -> None:
    """Retirement is an append, not an edit, and the reader follows it."""
    policy = _policy()
    await _seed_durable_receipt()
    await _lifecycle_through(
        policy,
        until_stage="authorized",
        activation_end=NOW - timedelta(minutes=30),
    )

    await _append(
        policy,
        stage="retired",
        effective_from=NOW - timedelta(minutes=30),
        effective_until=NOW + timedelta(hours=1),
    )
    evaluation = await _evaluate(policy)
    state = _state(evaluation, MARKET_DATA_QUERY_V2_CAPABILITY)

    assert evaluation.response.query_v2_enabled is False
    assert state.declared is False
    assert state.reason_code == "CAPABILITY_UNDECLARED"


@pytest.mark.asyncio
async def test_ledger_stays_append_only_for_updates_and_deletes() -> None:
    """An ORM edit or delete of a recorded attestation is refused.

    The guard lives in the mapper events, so it protects every session write.
    It does not cover a raw ``execute()`` DML statement, which is one more
    reason this service is the intended writer: the durable rows it produces
    can still only ever be superseded by a higher revision.
    """
    policy = _policy()
    await _append(
        policy,
        stage="declared",
        effective_from=NOW - timedelta(hours=1),
        effective_until=NOW,
    )

    async with async_session_maker() as session:
        record = (
            await session.scalars(
                select(MdCapabilityLedgerEntry).where(
                    MdCapabilityLedgerEntry.capability_id == MARKET_DATA_QUERY_V2_CAPABILITY
                )
            )
        ).one()
        original_revision = record.revision
        record.declared_capability = False
        with pytest.raises(ImmutableMarketDataRecordError):
            await session.flush()
        await session.rollback()

        with pytest.raises(ImmutableMarketDataRecordError):
            await session.delete(record)
            await session.flush()
        await session.rollback()

        survivors = (
            await session.scalars(
                select(MdCapabilityLedgerEntry).where(
                    MdCapabilityLedgerEntry.capability_id == MARKET_DATA_QUERY_V2_CAPABILITY
                )
            )
        ).all()
    assert [item.revision for item in survivors] == [original_revision]
    assert survivors[0].declared_capability is True


def test_request_contract_carries_no_caller_chosen_hashes() -> None:
    """descriptor_sha256 and evidence_sha256 are never inputs."""
    with pytest.raises(ValidationError):
        MarketDataCapabilityLedgerRecordRequest.model_validate(
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "verified",
                "effective_until": (NOW + timedelta(hours=1)).isoformat(),
                "verified_until": (NOW + timedelta(hours=2)).isoformat(),
                "evidence_sha256": "a" * 64,
            }
        )
    with pytest.raises(ValidationError):
        MarketDataCapabilityLedgerRecordRequest.model_validate(
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "declared",
                "effective_until": (NOW + timedelta(hours=1)).isoformat(),
                "descriptor_sha256": "b" * 64,
            }
        )
    with pytest.raises(ValidationError):
        MarketDataCapabilityLedgerRecordRequest.model_validate(
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "verified",
                "effective_until": (NOW + timedelta(hours=1)).isoformat(),
            }
        )
    with pytest.raises(ValidationError):
        MarketDataCapabilityLedgerRecordRequest.model_validate(
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "declared",
                "effective_until": (NOW + timedelta(hours=1)).isoformat(),
                "effective_from": (NOW + timedelta(hours=2)).isoformat(),
            }
        )


# ==================== HTTP surface ====================


@pytest.mark.asyncio
async def test_append_route_requires_an_authenticated_admin(
    client,
    auth_headers,
) -> None:
    """A normal authenticated user cannot append a deployment attestation."""
    body = {
        "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
        "stage": "declared",
        "effective_until": (NOW + timedelta(hours=1)).isoformat(),
    }
    unauthenticated = await client.post(LEDGER_ROUTE_PATH, json=body)
    forbidden = await client.post(LEDGER_ROUTE_PATH, json=body, headers=auth_headers)

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    async with async_session_maker() as session:
        assert (await session.scalars(select(MdCapabilityLedgerEntry))).all() == []


@pytest.mark.asyncio
async def test_admin_appends_full_lifecycle_and_effective_state_flips(
    client,
    auth_user,
    monkeypatch,
) -> None:
    """The operator path is usable end-to-end once durable receipts exist."""
    import app.api.data.queries as queries

    settings = _settings()
    monkeypatch.setattr(queries, "get_settings", lambda: settings)
    app.dependency_overrides[get_reviewed_market_data_source_policy] = lambda: _policy()
    base_time = datetime.now(UTC)
    try:
        user_data, headers = auth_user
        await _grant_admin(user_data["username"])
        await _seed_durable_receipt(base_time=base_time)

        bodies = [
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "declared",
                "effective_from": (base_time - timedelta(hours=4)).isoformat(),
                "effective_until": (base_time - timedelta(hours=3)).isoformat(),
            },
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "installed",
                "effective_from": (base_time - timedelta(hours=3)).isoformat(),
                "effective_until": (base_time - timedelta(hours=2)).isoformat(),
            },
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "verified",
                "effective_from": (base_time - timedelta(hours=2)).isoformat(),
                "effective_until": (base_time - timedelta(hours=1)).isoformat(),
                "verified_until": (base_time + timedelta(hours=6)).isoformat(),
            },
            {
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "authorized",
                "effective_from": (base_time - timedelta(hours=1)).isoformat(),
                "effective_until": (base_time + timedelta(hours=1)).isoformat(),
                "authorized_until": (base_time + timedelta(hours=1)).isoformat(),
            },
        ]
        responses = [
            await client.post(LEDGER_ROUTE_PATH, json=body, headers=headers) for body in bodies
        ]
        assert [response.status_code for response in responses] == [201, 201, 201, 201]
        receipt = responses[-1].json()
        assert receipt["verified_capability"] is True
        assert receipt["authorized_capability"] is True
        assert receipt["artifact_count"] == 1
        assert receipt["evidence_kind"] == "durable-verified-source-receipts-v1"

        rejected = await client.post(
            LEDGER_ROUTE_PATH,
            json={
                "capability_id": MARKET_DATA_QUERY_V2_CAPABILITY,
                "stage": "authorized",
                "effective_from": base_time.isoformat(),
                "effective_until": (base_time + timedelta(hours=1)).isoformat(),
                "authorized_until": (base_time + timedelta(hours=1)).isoformat(),
            },
            headers=headers,
        )
        assert rejected.status_code == 409
        assert rejected.json()["details"]["code"] == "CAPABILITY_LEDGER_ADMIN_WINDOW_OVERLAP"

        evidence = await client.get(
            (
                f"/api/v1/data/market-data/capability-ledger/records/"
                f"{MARKET_DATA_QUERY_V2_CAPABILITY}/evidence"
            ),
            params={"revision": receipt["revision"]},
            headers=headers,
        )
        assert evidence.status_code == 200
        assert evidence.json()["matches_stored"] is True
        assert evidence.json()["evidence_sha256"] == receipt["evidence_sha256"]

        effective = await client.get(
            "/api/v1/data/market-data/capability-ledger/effective", headers=headers
        )
        assert effective.status_code == 200
        assert effective.json()["query_v2_enabled"] is True
    finally:
        app.dependency_overrides.pop(get_reviewed_market_data_source_policy, None)


async def _grant_admin(username: str) -> None:
    async with async_session_maker() as session:
        user = (await session.scalars(select(User).where(User.username == username))).one()
        await session.execute(user_roles.insert().values(user_id=user.id, role=Role.ADMIN.value))
        await session.commit()
