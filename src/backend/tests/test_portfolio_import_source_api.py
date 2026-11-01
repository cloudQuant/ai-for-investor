"""Owner-scoped imported source versions through the real portfolio APIs."""

from __future__ import annotations

import asyncio
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "synthetic-import-source-test-secret-012345")

from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.portfolio.ledger import router as portfolio_ledger_router  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.models.portfolio_composition import PortfolioCompositionVersion  # noqa: E402
from app.models.portfolio_ledger import (  # noqa: E402
    PortfolioLedgerImportModel,
    PortfolioLedgerModel,
    PortfolioLedgerTransactionModel,
)
from app.schemas.auth import TokenPayload  # noqa: E402


def test_import_source_version_is_owner_scoped_preserved_and_not_valued() -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
            await connection.run_sync(PortfolioLedgerModel.__table__.create)
            await connection.run_sync(PortfolioLedgerImportModel.__table__.create)
            await connection.run_sync(PortfolioLedgerTransactionModel.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_db():
            async with session_maker() as session:
                yield session

        owner_subject = {"value": "owner-a"}
        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.include_router(portfolio_ledger_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: TokenPayload(
            sub=owner_subject["value"], username=owner_subject["value"]
        )
        app.dependency_overrides[get_db] = override_db

        rows = [
            {"symbol": "SYNTH-A", "trade_type": "buy", "quantity": 2, "price": 10},
            {
                "symbol": "SYNTH-B",
                "trade_type": "sell",
                "quantity": 1,
                "price": 12,
                "trade_date": "2026-10-12",
            },
            {
                "symbol": "SYNTH-C",
                "trade_type": "buy",
                "quantity": 1,
                "price": 8,
                "trade_date": "2026-10-12garbage",
            },
        ]
        source_payload = {
            "format": "json",
            "idempotency_key": "synthetic-import-version-1",
            "source_as_of": "2026-10-13",
            "source_currency": "USD",
            "transactions": rows,
        }

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                created_ledger = await client.post(
                    "/api/v1/portfolio-ledger",
                    json={
                        "name": "Synthetic imported records",
                        "base_currency": "USD",
                        "source_type": "imported",
                    },
                )
                assert created_ledger.status_code == 201, created_ledger.text
                ledger_id = created_ledger.json()["id"]

                imported_response = await client.post(
                    f"/api/v1/portfolio-ledger/{ledger_id}/import", json=source_payload
                )
                assert imported_response.status_code == 200, imported_response.text
                imported = imported_response.json()
                assert imported["duplicate"] is False
                assert imported["imported_count"] == 3
                assert imported["source_material_status"] == "verified"
                import_version_id = imported["import_version_id"]
                source_sha256 = imported["source_sha256"]
                assert len(source_sha256) == 64

                duplicate = await client.post(
                    f"/api/v1/portfolio-ledger/{ledger_id}/import", json=source_payload
                )
                assert duplicate.status_code == 200
                assert duplicate.json()["duplicate"] is True
                assert duplicate.json()["import_version_id"] == import_version_id
                assert duplicate.json()["source_sha256"] == source_sha256

                conflict = await client.post(
                    f"/api/v1/portfolio-ledger/{ledger_id}/import",
                    json={
                        **source_payload,
                        "transactions": [{"symbol": "CHANGED"}],
                    },
                )
                assert conflict.status_code == 409
                assert conflict.json()["detail"]["code"] == (
                    "PORTFOLIO_IMPORT_IDEMPOTENCY_CONFLICT"
                )

                source_list = await client.get("/api/v1/portfolio-ledger/imports")
                assert source_list.status_code == 200
                assert source_list.json()["total"] == 1
                assert source_list.json()["items"][0]["import_version_id"] == import_version_id
                assert source_list.json()["items"][0]["source_material_status"] == "verified"
                assert "source_document" not in source_list.json()["items"][0]

                source_detail = await client.get(
                    f"/api/v1/portfolio-ledger/imports/{import_version_id}"
                )
                assert source_detail.status_code == 200
                detail = source_detail.json()
                assert detail["source_sha256"] == source_sha256
                assert detail["source_document"]["transactions"] == rows
                assert "trade_date" not in detail["source_document"]["transactions"][0]

                composition = await client.post(
                    "/api/v1/portfolio/compositions",
                    json={
                        "portfolio_ref": "synthetic-import-view",
                        "source_type": "imported",
                        "base_currency": "USD",
                        "members": [{"kind": "imported_ledger", "ref": import_version_id}],
                    },
                )
                assert composition.status_code == 201, composition.text
                projection_response = await client.get(
                    "/api/v1/portfolio/overview",
                    params={
                        "portfolio_ref": "synthetic-import-view",
                        "membership_version": 1,
                    },
                )
                assert projection_response.status_code == 200, projection_response.text
                projection = projection_response.json()
                assert projection["source_type"] == "imported"
                assert projection["source_status"] == "imported_materials_projected"
                assert projection["creditable"] is False
                assert projection["overlap_policy"] == "non_additive_display_only"
                assert projection["source_facts"]["source_materials_verified"] is True
                artifact = projection["source_facts"]["artifacts"][0]
                assert artifact["import_version_id"] == import_version_id
                assert artifact["source_sha256"] == source_sha256
                assert artifact["source_as_of"] == "2026-10-13"
                assert artifact["source_currency"] == "USD"
                assert artifact["source_row_count"] == 3
                assert artifact["trade_date_rows_present"] == 1
                assert artifact["trade_date_coverage"] == "partial"
                assert artifact["freshness_status"] == "not_defined"
                assert artifact["source_rows_available"] is True
                assert "source_rows" not in artifact
                assert projection["account_total"] == {
                    "status": "not_applicable_imported",
                    "currency": None,
                    "value": None,
                }
                assert projection["accounts"] == []
                assert projection["strategies"] == []
                assert projection["strategy_attribution"]["attributed_value"] is None
                assert projection["coverage"]["complete"] is False
                assert projection["coverage"]["code"] == "IMPORTED_SOURCE_TRADE_DATES_INCOMPLETE"

                async with session_maker() as db:
                    normalized = list(
                        (
                            await db.scalars(
                                select(PortfolioLedgerTransactionModel).order_by(
                                    PortfolioLedgerTransactionModel.symbol
                                )
                            )
                        ).all()
                    )
                normalized_first = next(item for item in normalized if item.symbol == "SYNTH-A")
                assert normalized_first.trade_date == date.today().isoformat()
                # The projection date coverage above is derived from original JSON, not this
                # legacy normalized default date.

                async with session_maker() as db:
                    source = await db.get(PortfolioLedgerImportModel, import_version_id)
                    assert source is not None
                    source.source_document["transactions"][0]["symbol"] = "TAMPERED"
                    flag_modified(source, "source_document")
                    await db.commit()
                tampered_response = await client.get(
                    "/api/v1/portfolio/overview",
                    params={
                        "portfolio_ref": "synthetic-import-view",
                        "membership_version": 1,
                    },
                )
                tampered = tampered_response.json()
                assert tampered["source_status"] == "imported_material_integrity_invalid"
                assert tampered["source_facts"]["artifacts"][0]["status"] == "integrity_invalid"
                assert tampered["account_total"]["value"] is None
                assert "TAMPERED" not in tampered_response.text

                owner_subject["value"] = "owner-b"
                assert (await client.get("/api/v1/portfolio-ledger/imports")).json() == {
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 50,
                    "has_more": False,
                }
                foreign_detail = await client.get(
                    f"/api/v1/portfolio-ledger/imports/{import_version_id}"
                )
                assert foreign_detail.status_code == 404
                foreign_membership = await client.post(
                    "/api/v1/portfolio/compositions",
                    json={
                        "portfolio_ref": "foreign-import-view",
                        "source_type": "imported",
                        "base_currency": "USD",
                        "members": [{"kind": "imported_ledger", "ref": import_version_id}],
                    },
                )
                assert foreign_membership.status_code == 404
                foreign_projection = await client.get(
                    "/api/v1/portfolio/compositions/synthetic-import-view/versions/1/projection"
                )
                assert foreign_projection.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "source_payload",
    [
        {"transactions": [None]},
        {"transactions": [{"value": float("nan")}]},
        {"transactions": [], "source_as_of": "2026-02-30"},
        {"transactions": [], "source_currency": "usd"},
    ],
)
def test_import_source_contract_rejects_noncanonical_metadata(source_payload) -> None:
    from app.services.portfolio_import_source import (
        PortfolioImportSourceError,
        build_portfolio_import_source_document,
    )

    values = {
        "import_format": "json",
        "transactions": [],
        "source_as_of": None,
        "source_currency": None,
    }
    values.update(source_payload)
    with pytest.raises(PortfolioImportSourceError):
        build_portfolio_import_source_document(**values)


def test_import_source_integrity_hash_binds_json_scalar_types() -> None:
    from app.services.portfolio_import_source import (
        build_portfolio_import_source_document,
        portfolio_import_source_sha256,
        verify_portfolio_import_source,
    )

    source = build_portfolio_import_source_document(
        import_format="json",
        transactions=[{"flag": 1}],
        source_as_of=None,
        source_currency=None,
    )
    source_hash = portfolio_import_source_sha256(source)
    source["schema_version"] = True
    assert not verify_portfolio_import_source(
        document=source,
        expected_sha256=source_hash,
        expected_schema_version=1,
        import_format="json",
        imported_count=1,
        source_as_of=None,
        source_currency=None,
    )
