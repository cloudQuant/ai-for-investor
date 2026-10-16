"""Persisted AFI owners over the real SDK/ServiceHost read path."""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def test_persisted_owners_scope_real_http_sdk_service_host_and_portfolios(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind two persisted personal owners to distinct real service grants."""

    import httpx
    from fastapi import FastAPI

    from app.api.portfolio.compositions import router as composition_router
    from app.api.service_read import configure_service_read, router as service_read_router
    from app.db.database import get_db
    from app.models.portfolio_composition import PortfolioCompositionVersion
    from app.models.user import User
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.client import OrderBinding
    from app.services.service_read.session import SdkServiceReadSession
    from app.services.service_read.worker import ServiceReadWorker
    import app.config as app_config
    from app.utils import security
    from bt_api_py.service_execution import ServiceExecutionClient

    # R93's accepted helper module verifies that it was imported under its
    # own synthetic settings. Application modules are already loaded by this
    # test collection, so satisfy only that import-time helper assertion and
    # restore the production settings accessor immediately afterward.
    with monkeypatch.context() as config_patch:
        config_patch.setattr(
            app_config,
            "get_settings",
            lambda: SimpleNamespace(
                JWT_SECRET_KEY="service-read-integration-synthetic-jwt-key-0123456789",
                DATABASE_URL="sqlite+aiosqlite://",
                DEBUG=False,
            ),
        )
        from tests import test_service_read_authorized_http_integration as r93

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    app_db = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_db() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        async with app_db() as db:
            users = (
                User(
                    id=r93._SUBJECT_A,
                    username=r93._SUBJECT_A,
                    email=f"{r93._SUBJECT_A}@example.invalid",
                    hashed_password="synthetic-test-only",
                    is_active=True,
                    principal_kind="HUMAN",
                ),
                User(
                    id=r93._SUBJECT_B,
                    username=r93._SUBJECT_B,
                    email=f"{r93._SUBJECT_B}@example.invalid",
                    hashed_password="synthetic-test-only",
                    is_active=True,
                    principal_kind="HUMAN",
                ),
            )
            db.add_all(users)
            for subject, portfolio_ref, account_ref, strategy_ref in (
                (r93._SUBJECT_A, "portfolio-owner-a", r93._ACCOUNT_A, r93._STRATEGY_A),
                (r93._SUBJECT_B, "portfolio-owner-b", r93._ACCOUNT_B, r93._STRATEGY_B),
            ):
                db.add(
                    PortfolioCompositionVersion(
                        id=f"{portfolio_ref}-v1",
                        owner_subject=subject,
                        portfolio_ref=portfolio_ref,
                        membership_version=1,
                        source_type="live",
                        base_currency="USDT",
                        members=[
                            {"kind": "account", "ref": account_ref},
                            {"kind": "strategy", "ref": strategy_ref},
                        ],
                        membership_sha256=("a" if subject == r93._SUBJECT_A else "b") * 64,
                    )
                )
            await db.commit()

    asyncio.run(prepare_db())

    async def override_db():
        async with app_db() as db:
            yield db

    monkeypatch.setattr(
        security,
        "settings",
        SimpleNamespace(JWT_SECRET_KEY=r93._JWT_SECRET, JWT_ALGORITHM=r93._JWT_ALGORITHM),
    )
    app = FastAPI()
    app.include_router(service_read_router, prefix="/api/v1")
    app.include_router(composition_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db

    context = multiprocessing.get_context("spawn")
    endpoint = r93._order._endpoint()
    server_public, server_secret = r93.zmq.curve_keypair()
    keypairs = {
        name: r93.zmq.curve_keypair()
        for name in ("strategy_a", "strategy_b", "application")
    }
    keys: dict[str, bytes] = {"server_public": server_public, "server_secret": server_secret}
    for name, (public_key, secret_key) in keypairs.items():
        keys[f"{name}_public"] = public_key
        keys[f"{name}_secret"] = secret_key
    service_keys = {
        key: value
        for key, value in keys.items()
        if key.endswith("_public") or key == "server_secret"
    }

    host = None
    producer_runtimes: list[Any] = []
    workers: list[ServiceReadWorker] = []
    session_events: list[tuple[str, str, int]] = []
    identity_events: list[tuple[str, str, str, str, int]] = []
    events_lock = threading.Lock()
    main_thread_ident = threading.get_ident()
    try:
        host = r93._order._start_process(
            context,
            r93._multiuser_service_process,
            (
                r93._order._service_config(endpoint),
                str(tmp_path / "afi01-owner-service-registry.sqlite3"),
                service_keys,
                str(tmp_path / "afi01-owner-execution.sqlite3"),
            ),
            "afi01-persisted-owner-execution-host",
        )
        ready = r93._order._receive(host["pipe"], timeout=20.0)
        assert ready[0] == "ready", ready
        assert ready[2] == "started", ready

        strategy_profiles = (
            (
                "strategy_a",
                r93._STRATEGY_A_PRINCIPAL,
                r93._STRATEGY_A,
                r93._ENTRY_SCOPE_A,
                r93._SCOPE_A,
                r93._INTENT_A,
                "signal-owner-a",
            ),
            (
                "strategy_b",
                r93._STRATEGY_B_PRINCIPAL,
                r93._STRATEGY_B,
                r93._ENTRY_SCOPE_B,
                r93._SCOPE_B,
                r93._INTENT_B,
                "signal-owner-b",
            ),
        )
        for key_name, principal, actor, scope_ref, scope, intent_id, signal in strategy_profiles:
            identity = r93.WireIdentity(r93.WireRole.STRATEGY_CLIENT, principal, actor)
            runtime = r93._new_runtime(
                endpoint,
                role="strategy_client",
                security_ref=f"afi-{key_name}-curve-v1",
                keys={
                    **keys,
                    f"afi-{key_name}-curve-v1_public": keys[f"{key_name}_public"],
                    f"afi-{key_name}-curve-v1_secret": keys[f"{key_name}_secret"],
                },
                identity=identity,
                scope_ref=scope_ref,
                scope=scope,
            )
            producer_runtimes.append(runtime)
            assert runtime.start().degraded_count == 0
            submitter = ServiceExecutionClient(runtime, "broker.orders", scope_ref=scope_ref)
            r93._order._submit(submitter, intent_id, signal, "1")

        app_identities = (
            (
                r93._SUBJECT_A,
                r93._APPLICATION_IDENTITY_A,
                r93._ACCOUNT_A,
                r93._QUERY_SCOPE_A,
                r93._SCOPE_A,
                "afi-owner-a-dashboard-curve-v1",
            ),
            (
                r93._SUBJECT_B,
                r93._APPLICATION_IDENTITY_B,
                r93._ACCOUNT_B,
                r93._QUERY_SCOPE_B,
                r93._SCOPE_B,
                "afi-owner-b-dashboard-curve-v1",
            ),
        )

        async def exercise_http_body() -> None:
            access_by_subject: dict[str, ReadAccess] = {}
            for subject, identity, account_ref, query_scope, wire_scope, security_ref in app_identities:
                def make_session_factory(
                    *,
                    subject: str = subject,
                    identity: Any = identity,
                    query_scope: str = query_scope,
                    wire_scope: Any = wire_scope,
                    security_ref: str = security_ref,
                ):
                    def factory() -> Any:
                        owner = threading.current_thread()

                        def runtime_factory() -> Any:
                            with events_lock:
                                identity_events.append(
                                    (
                                        subject,
                                        identity.principal_ref,
                                        identity.actor_ref,
                                        identity.delegate_ref or "",
                                        threading.get_ident(),
                                    )
                                )
                            assert threading.current_thread() is owner
                            return r93._new_runtime(
                                endpoint,
                                role="application_client",
                                security_ref=security_ref,
                                keys={
                                    **keys,
                                    f"{security_ref}_public": keys["application_public"],
                                    f"{security_ref}_secret": keys["application_secret"],
                                },
                                identity=identity,
                                scope_ref=query_scope,
                                scope=wire_scope,
                            )

                        session = SdkServiceReadSession(
                            runtime_factory,
                            identity,
                            account_bindings={},
                            order_bindings={
                                query_scope: OrderBinding("application.order_query", query_scope)
                            },
                        )
                        return r93._ObservedSession(
                            session,
                            subject,
                            owner.ident,
                            session_events,
                            events_lock,
                        )

                    return factory

                worker = ServiceReadWorker(
                    make_session_factory(),
                    max_queue_size=8,
                    maintenance_interval_seconds=30.0,
                    name=f"afi01-persisted-owner-{subject}",
                )
                workers.append(worker)
                await worker.start()
                access_by_subject[subject] = ReadAccess(
                    worker,
                    allow_account_refs=frozenset({account_ref}),
                    allow_order_scope_refs=frozenset({query_scope}),
                )

            configure_service_read(ServiceReadAccessDirectory(access_by_subject))
            token_a = r93._make_token(r93._SUBJECT_A, r93._JWT_SECRET)
            token_b = r93._make_token(r93._SUBJECT_B, r93._JWT_SECRET)
            headers_a = {"Authorization": f"Bearer {token_a}"}
            headers_b = {"Authorization": f"Bearer {token_b}"}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://afi01-persisted-owner.synthetic.test",
            ) as client:
                own_a = await client.get(
                    f"/api/v1/service-read/orders/{r93._INTENT_A}",
                    params={"scope_ref": r93._QUERY_SCOPE_A},
                    headers={
                        **headers_a,
                        "X-User-Id": r93._SUBJECT_B,
                        "X-Actor-Ref": r93._SUBJECT_B,
                        "X-Principal-Ref": "forged-principal",
                        "X-Delegate-Ref": r93._DELEGATE_B,
                        "X-Tenant-Ref": r93._SUBJECT_B,
                        "X-Workspace-Id": "forged-workspace-b",
                    },
                )
                own_b = await client.get(
                    f"/api/v1/service-read/orders/{r93._INTENT_B}",
                    params={"scope_ref": r93._QUERY_SCOPE_B},
                    headers=headers_b,
                )
                assert own_a.status_code == own_b.status_code == 200
                assert own_a.json()["intent_id"] == r93._INTENT_A
                assert own_a.json()["state"] == "ACKED"
                assert own_b.json()["intent_id"] == r93._INTENT_B
                assert own_b.json()["state"] == "ACKED"

                own_portfolio_a = await client.get(
                    "/api/v1/portfolio/compositions/portfolio-owner-a/versions/1",
                    headers=headers_a,
                )
                own_portfolio_b = await client.get(
                    "/api/v1/portfolio/compositions/portfolio-owner-b/versions/1",
                    headers=headers_b,
                )
                assert own_portfolio_a.status_code == own_portfolio_b.status_code == 200
                assert own_portfolio_a.json()["members"] == [
                    {"kind": "account", "ref": r93._ACCOUNT_A},
                    {"kind": "strategy", "ref": r93._STRATEGY_A},
                ]
                assert own_portfolio_b.json()["members"] == [
                    {"kind": "account", "ref": r93._ACCOUNT_B},
                    {"kind": "strategy", "ref": r93._STRATEGY_B},
                ]

                counts_before_denials = r93._order._command(host, "counts")
                calls_before_denials = tuple(
                    event for event in session_events if event[1] in {"read_order", "read_account"}
                )
                cross_account = await client.get(
                    f"/api/v1/service-read/accounts/{r93._ACCOUNT_B}",
                    headers={
                        **headers_a,
                        "X-Tenant-Ref": r93._SUBJECT_B,
                        "X-Workspace-Id": "portfolio-owner-b",
                    },
                )
                cross_strategy = await client.get(
                    f"/api/v1/service-read/orders/{r93._INTENT_B}",
                    params={
                        "scope_ref": r93._QUERY_SCOPE_B,
                        "sub": r93._SUBJECT_B,
                        "actor_ref": r93._SUBJECT_B,
                        "principal_ref": r93._APP_PRINCIPAL,
                        "delegate_ref": r93._DELEGATE_B,
                        "tenant_ref": r93._SUBJECT_B,
                    },
                    headers={
                        **headers_a,
                        "X-User-Id": r93._SUBJECT_B,
                        "X-Actor-Ref": r93._SUBJECT_B,
                        "X-Principal-Ref": r93._APP_PRINCIPAL,
                        "X-Delegate-Ref": r93._DELEGATE_B,
                        "X-Tenant-Ref": r93._SUBJECT_B,
                    },
                )
                repeated_cross_strategy = await client.get(
                    f"/api/v1/service-read/orders/{r93._INTENT_B}",
                    params={"scope_ref": r93._QUERY_SCOPE_B},
                    headers={**headers_a, "X-Tenant-Ref": r93._SUBJECT_B},
                )
                cross_portfolio = await client.get(
                    "/api/v1/portfolio/compositions/portfolio-owner-a/versions/1",
                    params={"owner_subject": r93._SUBJECT_A, "tenant_ref": r93._SUBJECT_A},
                    headers={
                        **headers_b,
                        "X-Tenant-Ref": r93._SUBJECT_A,
                        "X-Workspace-Id": "portfolio-owner-a",
                    },
                )
                forged_owner_write = await client.post(
                    "/api/v1/portfolio/compositions",
                    headers={**headers_b, "X-Tenant-Ref": r93._SUBJECT_A},
                    json={
                        "owner_subject": r93._SUBJECT_A,
                        "portfolio_ref": "forged-owner-portfolio",
                        "source_type": "research",
                        "base_currency": "USD",
                        "members": [{"kind": "research_artifact", "ref": "artifact-a"}],
                    },
                )
                for response in (cross_account, cross_strategy, repeated_cross_strategy):
                    r93._assert_access_denied(response)
                assert cross_portfolio.status_code == 404
                assert forged_owner_write.status_code == 422
                assert tuple(
                    event
                    for event in session_events
                    if event[1] in {"read_order", "read_account"}
                ) == calls_before_denials
                assert r93._order._command(host, "counts") == counts_before_denials
                assert counts_before_denials[1] == (r93._INTENT_A, r93._INTENT_B)

        async def exercise_http() -> None:
            try:
                await exercise_http_body()
            finally:
                configure_service_read(None)
                closing_workers = tuple(workers)
                workers.clear()
                close_errors: list[BaseException] = []
                for worker in closing_workers:
                    try:
                        await worker.aclose()
                    except BaseException as error:
                        close_errors.append(error)
                assert not close_errors, [type(error).__name__ for error in close_errors]

        asyncio.run(exercise_http())
    finally:
        configure_service_read(None)
        for runtime in reversed(producer_runtimes):
            r93._close_runtime(runtime)
        if host is not None:
            process = host["process"]
            pipe = host["pipe"]
            closed = None
            close_error = None
            if process.is_alive():
                try:
                    pipe.send(("close",))
                    closed = r93._order._receive(pipe, timeout=10.0)
                except Exception as error:
                    close_error = type(error).__name__
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(10)
            process_still_alive = process.is_alive()
            exitcode = process.exitcode
            pipe.close()
            if not process_still_alive:
                process.close()
            assert not process_still_alive, "synthetic AFI01 ServiceHost remained alive after cleanup"
            assert close_error is None, close_error
            assert closed is not None and closed[0] == "closed", closed
            assert exitcode == 0
        asyncio.run(engine.dispose())

    assert len(identity_events) == 2
    assert {event[0] for event in identity_events} == {r93._SUBJECT_A, r93._SUBJECT_B}
    assert all(event[1] == r93._APP_PRINCIPAL and event[2] == event[0] for event in identity_events)
    assert all(
        event[3]
        == (r93._DELEGATE_A if event[0] == r93._SUBJECT_A else r93._DELEGATE_B)
        for event in identity_events
    )
    assert all(event[4] != main_thread_ident for event in identity_events)
    for subject, expected_order in (
        (r93._SUBJECT_A, r93._INTENT_A),
        (r93._SUBJECT_B, r93._INTENT_B),
    ):
        subject_events = [event for event in session_events if event[0] == subject]
        assert any(event[1] == "read_order" for event in subject_events)
        assert any(event[1] == "close" for event in subject_events)
        assert {event[2] for event in subject_events} == {identity_events[0 if subject == r93._SUBJECT_A else 1][4]}
