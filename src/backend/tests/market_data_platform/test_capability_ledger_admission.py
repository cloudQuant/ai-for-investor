"""Tests for the ledger writer that runs inside the v2 market-data query path.

The properties under test are the ones that make the writer worth having:

* a real admitted query -- including the query the durable gate refuses with
  ``503 MARKET_DATA_QUERY_V2_DISABLED`` -- appends exactly one current row per
  capability the reader itself enumerates, with the reader's own descriptor and
  a canonical evidence pre-image that this file restates literally;
* repeated admissions write nothing further (idempotency is per
  ``(capability, versioned pre-image)``, not per request);
* an observation row can never grant anything, and cannot claim verification
  even when a complete durable verified-receipt chain exists for that route;
* no request field, dependency double, or database failure can steer what is
  written.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.data.queries import (
    get_market_data_access_authorizer,
    get_market_data_capability_evaluation,
    get_market_data_query_service,
)
from app.db.database import async_session_maker
from app.main import app
from app.models.data_governance import DgDataset, DgProvider
from app.models.market_data_platform import (
    SOURCE_AUTHORIZATION_STATE_VERIFIED,
    MdCapabilityLedgerEntry,
    MdDataSeries,
    MdObservationRevision,
    MdPublication,
    MdSourceSnapshot,
)
from app.services.market_data.access import (
    MarketDataAccessAuthorizer,
    MarketDataAuthorizationError,
    MarketDataPrincipal,
)
from app.services.market_data.capability_ledger import (
    MARKET_DATA_DEFAULT_POLICY_ID,
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
    MarketDataCapabilityLedger,
    rollout_capability_descriptor_sha256,
    route_capability_descriptor_sha256,
    route_capability_id,
)
from app.services.market_data.capability_ledger_admission import (
    ADMISSION_OBSERVATION_KIND,
    ADMISSION_OBSERVATION_VERSION,
    DEFAULT_OBSERVATION_WINDOW,
    record_admission_observations,
)
from app.services.market_data.query_service import MarketDataQueryService
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
    MarketDataSourcePolicyRegistry,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
PROVIDER_ID = "admission-akshare"
ROUTE_ID = "admission-stock-primary-v1"
QUERY_SURFACE = f"{MarketDataQueryService.__module__}.{MarketDataQueryService.__qualname__}"
ROLLOUT_CAPABILITY_IDS = (
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
)


class _NoNetworkProvider:
    async def fetch(self, _request: object) -> object:
        raise AssertionError("admission ledger tests must not call providers")


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    """Restate the ledger canonical digest independently of the implementation."""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expected_evidence_sha256(
    *,
    capability_id: str,
    scope: str,
    route_id: str | None,
    descriptor_sha256: str,
    installed: bool,
    installed_surface: str | None,
) -> str:
    return _canonical(
        {
            "version": ADMISSION_OBSERVATION_VERSION,
            "observation_kind": ADMISSION_OBSERVATION_KIND,
            "capability_id": capability_id,
            "scope": scope,
            "policy_id": MARKET_DATA_DEFAULT_POLICY_ID,
            "route_id": route_id,
            "descriptor_sha256": descriptor_sha256,
            "declared_observed": True,
            "installed_observed": installed,
            "installed_surface": installed_surface,
        }
    )


def _settings(**overrides: bool) -> SimpleNamespace:
    values: dict[str, object] = {
        "MARKET_DATA_QUERY_V2_ENABLED": True,
        "MARKET_DATA_ONLINE_FETCH_ENABLED": True,
        "MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED": True,
        "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED": True,
        "MARKET_DATA_OPENBB_PROVIDER": "yfinance",
        "MARKET_DATA_OPENBB_ALLOWED_MARKETS": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _route(route_id: str = ROUTE_ID) -> MarketDataProviderRoute:
    return MarketDataProviderRoute(
        route_id=route_id,
        request_provider=PROVIDER_ID,
        expected_result_provider_ids=frozenset({PROVIDER_ID}),
        asset_types=frozenset({"stock"}),
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
        policy_id=MARKET_DATA_DEFAULT_POLICY_ID,
        allowed_purposes=frozenset({"display", "research"}),
        routes=routes or (_route(),),
    )


class _AccessAuthorizer(MarketDataAccessAuthorizer):
    """Deterministic data-read authorization stand-in."""

    def __init__(self, principal: MarketDataPrincipal) -> None:
        self.principal = principal

    async def principal_for_user(self, _user: object) -> MarketDataPrincipal:
        return self.principal

    async def revalidate_principal(self, *, principal: MarketDataPrincipal) -> MarketDataPrincipal:
        return principal

    @staticmethod
    def require_read_data(*, principal: MarketDataPrincipal) -> None:
        if not principal.can_read_data:
            raise MarketDataAuthorizationError("MARKET_DATA_READ_ENTITLEMENT_DENIED")


def _principal() -> MarketDataPrincipal:
    return MarketDataPrincipal(
        principal_id="user-1",
        principal_scope="principal-v1:test-user",
        tenant_scope="default",
        roles=("user",),
        permissions=("data:read",),
        entitlement_revision="e" * 64,
    )


class _RefusingService:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("an unattested capability must reject before execution")


def _query_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identity": {"canonical_id": "instrument:stock:CN-SSE:600000"},
        "dataset_code": "market.stock_daily",
        "data_kind": "bars",
        "frequency": "1d",
        "family_id": "stock.realtime",
        "family_contract_version": "market-data-family-v1",
        "start": "2026-09-08T09:00:00+00:00",
        "end": "2026-09-08T12:00:00+00:00",
        "required_fields": ["close"],
        "source_policy_id": MARKET_DATA_DEFAULT_POLICY_ID,
    }
    payload.update(overrides)
    return payload


async def _post_query(
    client: Any,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict[str, object] | None = None,
) -> tuple[Any, _RefusingService]:
    """Send one real v2 query through the installed route with the real evaluator."""
    import app.api.data.queries as queries

    authorizer = _AccessAuthorizer(_principal())
    service = _RefusingService()
    monkeypatch.setattr(queries, "get_settings", lambda: _settings())
    app.dependency_overrides[get_market_data_access_authorizer] = lambda: authorizer
    app.dependency_overrides[get_market_data_query_service] = lambda: service
    try:
        response = await client.post(
            "/api/v1/data/queries",
            json=payload or _query_payload(),
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_market_data_access_authorizer, None)
        app.dependency_overrides.pop(get_market_data_query_service, None)
    return response, service


async def _ledger_rows() -> list[MdCapabilityLedgerEntry]:
    async with async_session_maker() as session:
        return list(
            (
                await session.scalars(
                    select(MdCapabilityLedgerEntry).order_by(
                        MdCapabilityLedgerEntry.capability_id,
                        MdCapabilityLedgerEntry.revision,
                    )
                )
            ).all()
        )


async def _reviewed_evaluation() -> Any:
    """Run the real durable evaluator over this build's reviewed policy."""
    import app.api.data.queries as queries

    settings = _settings()
    async with async_session_maker() as session:
        # No frozen clock: the admission writer stamps the real deployment
        # instant, so the read-back must use the same instant to be honest.
        return await MarketDataCapabilityLedger(session).evaluate(
            settings=settings,
            source_policies=queries._source_policies_from_settings(settings),
        )


def _expected_definitions(evaluation: Any) -> list[dict[str, Any]]:
    """Enumerate the capabilities the durable reader itself expects to see."""
    policy = evaluation.effective_source_policies.resolve(MARKET_DATA_DEFAULT_POLICY_ID)
    expected = [
        {
            "capability_id": capability_id,
            "scope": "rollout",
            "route_id": None,
            "descriptor_sha256": rollout_capability_descriptor_sha256(capability_id),
            "installed": True,
            "installed_surface": QUERY_SURFACE,
        }
        for capability_id in ROLLOUT_CAPABILITY_IDS
    ]
    expected.extend(
        {
            "capability_id": route_capability_id(route.route_id),
            "scope": "route",
            "route_id": route.route_id,
            "descriptor_sha256": route_capability_descriptor_sha256(route),
            "installed": callable(getattr(route.adapter, "fetch", None)),
            "installed_surface": _surface(route.adapter),
        }
        for route in policy.routes
    )
    return expected


def _surface(adapter: object) -> str:
    return f"{type(adapter).__module__}.{type(adapter).__qualname__}"


# ---------------------------------------------------------------------------
# (a) a real query through the serving path produces the expected ledger rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admitted_query_appends_one_observed_row_per_capability(
    client, auth_headers, monkeypatch
) -> None:
    """The refused v2 query still records what this build actually observed."""
    response, service = await _post_query(client, auth_headers, monkeypatch)

    assert response.status_code == 503
    assert response.json()["details"] == {"code": "MARKET_DATA_QUERY_V2_DISABLED"}
    assert service.calls == 0

    expected = _expected_definitions(await _reviewed_evaluation())
    rows = {row.capability_id: row for row in await _ledger_rows()}

    assert set(rows) == {item["capability_id"] for item in expected}
    assert rows, "the serving path must record at least one capability"

    for item in expected:
        row = rows[item["capability_id"]]
        assert row.revision == 1
        assert row.descriptor_sha256 == item["descriptor_sha256"]
        assert row.evidence_sha256 == _expected_evidence_sha256(**item)
        assert row.declared_capability is True
        assert row.installed_capability is item["installed"]
        # The two facts only an operator decision can supply stay unclaimed.
        assert row.verified_capability is False
        assert row.verified_at is None
        assert row.verified_until is None
        assert row.authorized_capability is False
        assert row.authorized_at is None
        assert row.authorized_until is None
        assert row.effective_until is not None
        assert row.effective_until - row.effective_from == DEFAULT_OBSERVATION_WINDOW


@pytest.mark.asyncio
async def test_repeated_admissions_are_idempotent_per_pre_image(
    client, auth_headers, monkeypatch
) -> None:
    """Three admissions of one build append one row per capability, not three."""
    for _ in range(3):
        response, _service = await _post_query(client, auth_headers, monkeypatch)
        assert response.status_code == 503

    rows = await _ledger_rows()
    assert rows
    grouped: dict[str, int] = {}
    for row in rows:
        grouped[row.capability_id] = grouped.get(row.capability_id, 0) + 1
    assert all(count == 1 for count in grouped.values())
    assert {row.revision for row in rows} == {1}


@pytest.mark.asyncio
async def test_observed_rows_never_enable_a_capability(client, auth_headers, monkeypatch) -> None:
    """A declaration/installation observation cannot mint an effective capability."""
    response, _service = await _post_query(client, auth_headers, monkeypatch)
    assert response.status_code == 503

    evaluation = await _reviewed_evaluation()
    states = {state.capability_id: state for state in evaluation.response.capability_states}
    assert states
    for state in states.values():
        assert state.effective is False
        assert state.declared is True
        assert state.installed is True
        assert state.verified is False
        assert state.authorized is False
        assert state.reason_code == "CAPABILITY_NOT_VERIFIED"
    assert evaluation.response.query_v2_enabled is False
    assert evaluation.effective_route_ids == frozenset()


@pytest.mark.asyncio
async def test_request_content_cannot_select_a_capability_or_digest(
    client, auth_headers, monkeypatch
) -> None:
    """Every recorded digest is the reviewed policy's, never a request-derived value."""
    hostile = _query_payload(
        identity={"canonical_id": "instrument:stock:CN-SZSE:000001"},
        dataset_code="market.stock_daily",
        required_fields=["close"],
    )
    response, _service = await _post_query(client, auth_headers, monkeypatch, payload=hostile)
    assert response.status_code == 503

    expected = {
        item["capability_id"]: item for item in _expected_definitions(await _reviewed_evaluation())
    }
    rows = {row.capability_id: row for row in await _ledger_rows()}

    assert set(rows) == set(expected)
    for capability_id, item in expected.items():
        assert rows[capability_id].descriptor_sha256 == item["descriptor_sha256"]
        assert rows[capability_id].evidence_sha256 == _expected_evidence_sha256(**item)


@pytest.mark.asyncio
async def test_writer_refuses_to_create_a_second_current_record(
    client, auth_headers, monkeypatch
) -> None:
    """An open-ended operator window is never overlapped; overlap reads ambiguous."""
    policy = (await _reviewed_evaluation()).effective_source_policies.resolve(
        MARKET_DATA_DEFAULT_POLICY_ID
    )
    route = policy.routes[0]
    capability_id = route_capability_id(route.route_id)
    real_now = datetime.now(UTC)
    async with async_session_maker() as session:
        session.add(
            MdCapabilityLedgerEntry(
                capability_id=capability_id,
                revision=1,
                descriptor_sha256=route_capability_descriptor_sha256(route),
                evidence_sha256=_sha("operator-attestation", capability_id),
                declared_capability=True,
                installed_capability=True,
                verified_capability=True,
                verified_at=real_now - timedelta(hours=1),
                verified_until=real_now + timedelta(hours=6),
                authorized_capability=True,
                authorized_at=real_now - timedelta(hours=1),
                authorized_until=real_now + timedelta(hours=6),
                effective_from=real_now - timedelta(hours=2),
                effective_until=None,
            )
        )
        await session.commit()

    response, _service = await _post_query(client, auth_headers, monkeypatch)
    assert response.status_code == 503

    rows = await _ledger_rows()
    protected = [row for row in rows if row.capability_id == capability_id]
    assert len(protected) == 1
    assert protected[0].revision == 1
    assert protected[0].authorized_capability is True
    # The remaining capabilities are still recorded, so the skip is targeted.
    assert any(row.capability_id != capability_id for row in rows)


@pytest.mark.asyncio
async def test_dependency_double_produces_no_ledger_row(client, auth_headers, monkeypatch) -> None:
    """A value the writer cannot inspect is not evidence, so nothing is written."""
    import app.api.data.queries as queries

    monkeypatch.setattr(queries, "get_settings", lambda: _settings())
    app.dependency_overrides[get_market_data_access_authorizer] = lambda: _AccessAuthorizer(
        _principal()
    )
    app.dependency_overrides[get_market_data_query_service] = lambda: _RefusingService()
    fake = SimpleNamespace(
        response=SimpleNamespace(query_v2_enabled=False, research_cache_fill_enabled=False),
        effective_source_policies=object(),
        effective_route_ids=frozenset(),
    )
    app.dependency_overrides[get_market_data_capability_evaluation] = lambda: fake
    try:
        response = await client.post(
            "/api/v1/data/queries",
            json=_query_payload(),
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_market_data_capability_evaluation, None)
        app.dependency_overrides.pop(get_market_data_access_authorizer, None)
        app.dependency_overrides.pop(get_market_data_query_service, None)

    assert response.status_code == 503
    assert await _ledger_rows() == []


# ---------------------------------------------------------------------------
# (b) counterfactuals at the service boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_is_not_claimed_even_when_durable_receipts_exist() -> None:
    """Real verified receipts do not let the admission writer claim verification."""
    policy = _policy()
    route = policy.routes[0]
    await _seed_verified_receipt()

    async with async_session_maker() as session:
        sealed = await session.scalar(
            select(func.count())
            .select_from(MdSourceSnapshot)
            .join(
                MdPublication,
                and_(
                    MdPublication.entity_type == "source_snapshot",
                    MdPublication.entity_id == MdSourceSnapshot.id,
                ),
            )
            .where(
                MdSourceSnapshot.source_authorization_state == SOURCE_AUTHORIZATION_STATE_VERIFIED,
                MdSourceSnapshot.source_authorization_descriptor_sha256.is_not(None),
                MdPublication.entity_sha256 == MdSourceSnapshot.payload_sha256,
                MdPublication.published_at.is_not(None),
            )
        )
        # The receipts a verification claim would need really are in the database.
        assert sealed is not None and sealed >= 1

        evaluation = await MarketDataCapabilityLedger(session, clock=lambda: NOW).evaluate(
            settings=_settings(),
            source_policies=MarketDataSourcePolicyRegistry((policy,)),
        )
        result = await record_admission_observations(session, evaluation, clock=lambda: NOW)

    assert result is not None
    assert result.recorded_count >= 1
    rows = {row.capability_id: row for row in await _ledger_rows()}
    observed = rows[route_capability_id(route.route_id)]
    assert observed.verified_capability is False
    assert observed.authorized_capability is False
    assert observed.evidence_sha256 == _expected_evidence_sha256(
        capability_id=route_capability_id(route.route_id),
        scope="route",
        route_id=route.route_id,
        descriptor_sha256=route_capability_descriptor_sha256(route),
        installed=True,
        installed_surface=_surface(route.adapter),
    )


@pytest.mark.asyncio
async def test_second_admission_of_the_same_pre_image_writes_nothing() -> None:
    """The pre-image, not the wall clock, is the idempotency key."""
    import app.api.data.queries as queries

    settings = _settings()
    async with async_session_maker() as session:
        evaluation = await MarketDataCapabilityLedger(session, clock=lambda: NOW).evaluate(
            settings=settings,
            source_policies=queries._source_policies_from_settings(settings),
        )
        first = await record_admission_observations(session, evaluation, clock=lambda: NOW)
        second = await record_admission_observations(
            session, evaluation, clock=lambda: NOW + timedelta(seconds=1)
        )

    assert first is not None and first.recorded_count >= 1
    assert second is not None
    assert second.recorded_capability_ids == ()
    assert set(second.skipped_capability_ids) == set(first.recorded_capability_ids)
    rows = await _ledger_rows()
    assert len(rows) == first.recorded_count
    assert {row.revision for row in rows} == {1}


@pytest.mark.asyncio
async def test_descriptor_change_appends_a_new_revision_after_the_window() -> None:
    """A changed reviewed route is a new pre-image, never an in-place edit."""
    async with async_session_maker() as session:
        evaluation = await MarketDataCapabilityLedger(session, clock=lambda: NOW).evaluate(
            settings=_settings(),
            source_policies=MarketDataSourcePolicyRegistry((_policy(),)),
        )
        await record_admission_observations(session, evaluation, clock=lambda: NOW)

    later = NOW + DEFAULT_OBSERVATION_WINDOW
    changed_route = replace(_route(), markets=frozenset({"CN-SZSE"}))
    async with async_session_maker() as session:
        changed_evaluation = await MarketDataCapabilityLedger(
            session, clock=lambda: later
        ).evaluate(
            settings=_settings(),
            source_policies=MarketDataSourcePolicyRegistry((_policy(changed_route),)),
        )
        result = await record_admission_observations(
            session, changed_evaluation, clock=lambda: later
        )

    assert result is not None and result.recorded_count >= 1
    rows = [
        row for row in await _ledger_rows() if row.capability_id == route_capability_id(ROUTE_ID)
    ]
    assert [row.revision for row in rows] == [1, 2]
    assert len({row.descriptor_sha256 for row in rows}) == 2


@pytest.mark.asyncio
async def test_unreadable_ledger_is_skipped_without_raising() -> None:
    """A missing migration or dead pool cannot break or silently 'record' a query."""
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as orphan_session:
            with pytest.raises(SQLAlchemyError):
                await orphan_session.execute(select(MdCapabilityLedgerEntry))
            evaluation = await _reviewed_evaluation()
            result = await record_admission_observations(
                orphan_session, evaluation, clock=lambda: NOW
            )
        assert result is not None
        assert result.recorded_capability_ids == ()
        assert await _ledger_rows() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_requires_a_real_evaluation_and_session() -> None:
    """Non-inspectable inputs are refused rather than described."""
    evaluation = await _reviewed_evaluation()
    assert await record_admission_observations(object(), evaluation, clock=lambda: NOW) is None
    async with async_session_maker() as session:
        assert await record_admission_observations(session, object(), clock=lambda: NOW) is None
    assert await _ledger_rows() == []


@pytest.mark.asyncio
async def test_concurrent_admissions_record_one_row_per_capability() -> None:
    """Simultaneous admissions cannot leave the ledger with two current records."""
    import app.api.data.queries as queries

    settings = _settings()
    async with async_session_maker() as session:
        evaluation = await MarketDataCapabilityLedger(session, clock=lambda: NOW).evaluate(
            settings=settings,
            source_policies=queries._source_policies_from_settings(settings),
        )

    async def _one_admission() -> None:
        async with async_session_maker() as session:
            await record_admission_observations(session, evaluation, clock=lambda: NOW)

    await asyncio.gather(*[_one_admission() for _ in range(4)])

    rows = await _ledger_rows()
    assert rows
    grouped: dict[str, int] = {}
    for row in rows:
        grouped[row.capability_id] = grouped.get(row.capability_id, 0) + 1
    assert all(count == 1 for count in grouped.values()), grouped


async def _seed_verified_receipt() -> str:
    """Persist one complete verified + sealed fetch chain attributable to a route."""
    retrieved_at = NOW - timedelta(hours=3)
    payload_sha256 = _sha("payload")
    async with async_session_maker() as session:
        provider = DgProvider(
            provider_id=PROVIDER_ID,
            name="Admission ledger source",
            category="market",
            is_active=True,
        )
        session.add(provider)
        await session.flush()
        dataset = DgDataset(
            dataset_code="market.admission_daily",
            display_name="Admission ledger dataset",
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
            adapter_id="admission-adapter",
            endpoint_version="test-v1",
            request_fingerprint_sha256=_sha("request"),
            provider_request_id="a" * 32,
            provider_request_fingerprint_sha256=_sha("provider"),
            query_fingerprint_sha256=_sha("query"),
            source_authorization_state=SOURCE_AUTHORIZATION_STATE_VERIFIED,
            source_authorization_descriptor_sha256=_sha("grant"),
            payload_sha256=payload_sha256,
            request_json={
                "resolved_query": {
                    "source_policy_id": MARKET_DATA_DEFAULT_POLICY_ID,
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
                entity_sha256=payload_sha256,
                published_at=retrieved_at + timedelta(minutes=1),
                visibility_sequence=1,
            )
        )
        series = MdDataSeries(
            dataset_id=str(dataset.id),
            canonical_id="instrument:stock:CN-SSE:600000",
            data_kind="bars",
            frequency="1d",
            semantic_key_sha256=_sha("series"),
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
                fields_sha256=_sha("fields"),
                revision_number=1,
                revision_key_sha256=_sha("revision"),
                normalization_version="test-v1",
                provenance_json={},
                committed_at=retrieved_at + timedelta(minutes=1),
            )
        )
        await session.commit()
        return str(snapshot.id)


@pytest.mark.asyncio
async def test_admission_writer_does_not_commit_caller_session_and_attested_supersedes() -> None:
    """Admission writes use an isolated transaction and operator-attested rows supersede them."""
    policy = _policy()
    route = policy.routes[0]
    registry = MarketDataSourcePolicyRegistry((policy,))

    async with async_session_maker() as caller_session:
        evaluation = await MarketDataCapabilityLedger(caller_session, clock=lambda: NOW).evaluate(
            settings=_settings(),
            source_policies=registry,
        )
        caller_commits = 0
        original_commit = caller_session.commit

        async def _tracking_commit() -> None:
            nonlocal caller_commits
            caller_commits += 1
            await original_commit()

        caller_session.commit = _tracking_commit  # type: ignore[method-assign]
        try:
            result = await record_admission_observations(
                caller_session, evaluation, clock=lambda: NOW
            )
        finally:
            caller_session.commit = original_commit  # type: ignore[method-assign]

        assert caller_commits == 0
        assert result is not None and result.recorded_count >= 1

    # Add overlapping operator-attested rows for query_v2 and the route capability and verify they
    # supersede the unattested admission-observation rows without raising CAPABILITY_LEDGER_AMBIGUOUS.
    route_cap_id = route_capability_id(route.route_id)
    attested_targets = (
        (
            MARKET_DATA_QUERY_V2_CAPABILITY,
            rollout_capability_descriptor_sha256(MARKET_DATA_QUERY_V2_CAPABILITY),
        ),
        (
            route_cap_id,
            route_capability_descriptor_sha256(route),
        ),
    )
    async with async_session_maker() as seed_session:
        for cap_id, descriptor_sha in attested_targets:
            seed_session.add(
                MdCapabilityLedgerEntry(
                    capability_id=cap_id,
                    revision=99,
                    descriptor_sha256=descriptor_sha,
                    evidence_sha256=_sha("operator-attested", cap_id),
                    declared_capability=True,
                    installed_capability=True,
                    verified_capability=True,
                    verified_at=NOW - timedelta(minutes=10),
                    verified_until=NOW + timedelta(hours=1),
                    authorized_capability=True,
                    authorized_at=NOW - timedelta(minutes=10),
                    authorized_until=NOW + timedelta(hours=1),
                    effective_from=NOW - timedelta(minutes=10),
                    effective_until=NOW + timedelta(hours=1),
                )
            )
        await seed_session.commit()

    async with async_session_maker() as verify_session:
        evaluated = await MarketDataCapabilityLedger(
            verify_session, clock=lambda: NOW + timedelta(minutes=1)
        ).evaluate(
            settings=_settings(),
            source_policies=registry,
        )
    assert evaluated.route_is_effective(route.route_id) is True
