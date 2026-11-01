from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_ledger import (
    PortfolioLedgerImportModel,
    PortfolioLedgerModel,
    PortfolioLedgerSnapshotModel,
    PortfolioLedgerTransactionModel,
)
from app.services.portfolio_import_source import (
    PortfolioImportSourceError,
    build_portfolio_import_source_document,
    portfolio_import_source_sha256,
    verify_portfolio_import_source,
)

_BASE_NAV = 1_000_000.0
_POSITION_TRADE_TYPES = {"buy", "sell"}


class PortfolioLedgerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_portfolio(
        self,
        user_id: str,
        name: str,
        base_currency: str,
        source_type: str,
        *,
        benchmark_symbol: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        portfolio = PortfolioLedgerModel(
            owner_id=user_id,
            name=name,
            base_currency=base_currency,
            source_type=source_type,
            benchmark_symbol=str(benchmark_symbol or "").strip() or None,
            tags=self._normalize_tags(tags),
            notes=str(notes or "").strip() or None,
        )
        self.db.add(portfolio)
        await self.db.commit()
        await self.db.refresh(portfolio)
        return self._serialize_portfolio(portfolio, transaction_count=0)

    async def get_portfolio(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        return self._serialize_portfolio(
            portfolio,
            transaction_count=await self._transaction_count(portfolio_id),
        )

    async def list_portfolios(self, user_id: str) -> dict[str, Any]:
        result = await self.db.execute(
            select(PortfolioLedgerModel)
            .where(PortfolioLedgerModel.owner_id == user_id)
            .order_by(
                PortfolioLedgerModel.updated_at.desc(), PortfolioLedgerModel.created_at.desc()
            )
        )
        portfolios = list(result.scalars().all())
        items = [
            self._serialize_portfolio(
                portfolio,
                transaction_count=await self._transaction_count(str(portfolio.id)),
            )
            for portfolio in portfolios
        ]
        return {"items": items, "total": len(items)}

    async def list_import_sources(
        self, user_id: str, *, page: int = 1, page_size: int = 50
    ) -> dict[str, Any]:
        """List this owner's immutable import versions without returning row contents."""

        query = (
            select(PortfolioLedgerImportModel, PortfolioLedgerModel)
            .join(
                PortfolioLedgerModel,
                PortfolioLedgerModel.id == PortfolioLedgerImportModel.portfolio_id,
            )
            .where(PortfolioLedgerModel.owner_id == user_id)
            .order_by(
                PortfolioLedgerImportModel.created_at.desc(),
                PortfolioLedgerImportModel.id.asc(),
            )
        )
        total = int(
            await self.db.scalar(
                select(func.count())
                .select_from(PortfolioLedgerImportModel)
                .join(
                    PortfolioLedgerModel,
                    PortfolioLedgerModel.id == PortfolioLedgerImportModel.portfolio_id,
                )
                .where(PortfolioLedgerModel.owner_id == user_id)
            )
            or 0
        )
        result = await self.db.execute(query.offset((page - 1) * page_size).limit(page_size))
        items: list[dict[str, Any]] = []
        for imported, portfolio in result.all():
            material_status = _import_material_status(imported)
            items.append(
                {
                    "import_version_id": imported.id,
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "base_currency": portfolio.base_currency,
                    "import_format": imported.import_format,
                    "imported_count": imported.imported_count,
                    "source_material_status": material_status,
                    "source_as_of": imported.source_as_of
                    if material_status == "verified"
                    else None,
                    "source_currency": (
                        imported.source_currency if material_status == "verified" else None
                    ),
                    "source_sha256": imported.source_sha256
                    if material_status == "verified"
                    else None,
                    "created_at": imported.created_at.isoformat(),
                }
            )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
        }

    async def get_import_source(
        self, user_id: str, import_version_id: str
    ) -> dict[str, Any] | None:
        """Return one owner's verified raw import document, never a normalized ledger."""

        result = await self.db.execute(
            select(PortfolioLedgerImportModel, PortfolioLedgerModel)
            .join(
                PortfolioLedgerModel,
                PortfolioLedgerModel.id == PortfolioLedgerImportModel.portfolio_id,
            )
            .where(
                PortfolioLedgerImportModel.id == import_version_id,
                PortfolioLedgerModel.owner_id == user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        imported, portfolio = row
        material_status = _import_material_status(imported)
        return {
            "import_version_id": imported.id,
            "portfolio_id": portfolio.id,
            "portfolio_name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "import_format": imported.import_format,
            "imported_count": imported.imported_count,
            "source_material_status": material_status,
            "source_schema_version": (
                imported.source_schema_version if material_status == "verified" else None
            ),
            "source_sha256": imported.source_sha256 if material_status == "verified" else None,
            "source_as_of": imported.source_as_of if material_status == "verified" else None,
            "source_currency": imported.source_currency if material_status == "verified" else None,
            "source_document": (
                imported.source_document if material_status == "verified" else None
            ),
            "created_at": imported.created_at.isoformat(),
        }

    async def list_transactions(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        return {
            "items": [self._serialize_transaction(item) for item in transactions],
            "total": len(transactions),
        }

    async def import_transactions(
        self,
        user_id: str,
        portfolio_id: str,
        *,
        idempotency_key: str,
        transactions: list[dict[str, Any]],
        import_format: str = "json",
        source_as_of: str | None = None,
        source_currency: str | None = None,
    ) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        try:
            source_document = build_portfolio_import_source_document(
                import_format=import_format,
                transactions=transactions,
                source_as_of=source_as_of,
                source_currency=source_currency,
            )
            source_sha256 = portfolio_import_source_sha256(source_document)
        except PortfolioImportSourceError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "PORTFOLIO_IMPORT_SOURCE_INVALID"},
            ) from error
        existing_import = await self.db.execute(
            select(PortfolioLedgerImportModel).where(
                PortfolioLedgerImportModel.portfolio_id == portfolio_id,
                PortfolioLedgerImportModel.idempotency_key == idempotency_key,
            )
        )
        existing = existing_import.scalar_one_or_none()
        if existing is not None:
            existing_is_verified = verify_portfolio_import_source(
                document=existing.source_document,
                expected_sha256=existing.source_sha256,
                expected_schema_version=existing.source_schema_version,
                import_format=existing.import_format,
                imported_count=existing.imported_count,
                source_as_of=existing.source_as_of,
                source_currency=existing.source_currency,
            )
            if existing_is_verified and existing.source_sha256 != source_sha256:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "PORTFOLIO_IMPORT_IDEMPOTENCY_CONFLICT"},
                )
            material_status = (
                "verified"
                if existing_is_verified
                else (
                    "integrity_invalid"
                    if existing.source_document is not None or existing.source_sha256 is not None
                    else "unavailable_legacy"
                )
            )
            return {
                "duplicate": True,
                "imported_count": 0,
                "import_version_id": existing.id,
                "source_sha256": existing.source_sha256 if existing_is_verified else None,
                "source_material_status": material_status,
            }
        imported_count = 0
        for item in transactions:
            quantity = float(item.get("quantity") or 0.0)
            price = float(item.get("price") or 0.0)
            amount_raw = item.get("amount")
            amount = float(amount_raw) if amount_raw is not None else round(quantity * price, 2)
            self.db.add(
                PortfolioLedgerTransactionModel(
                    portfolio_id=portfolio_id,
                    symbol=str(item.get("symbol") or "").strip(),
                    trade_type=str(item.get("trade_type") or "buy").strip().lower(),
                    quantity=quantity,
                    price=price,
                    amount=amount,
                    trade_date=str(item.get("trade_date") or str(date.today())),
                    benchmark_symbol=(
                        str(
                            item.get("benchmark_symbol") or portfolio.benchmark_symbol or ""
                        ).strip()
                        or None
                    ),
                    tags=self._normalize_tags(item.get("tags")),
                    notes=str(item.get("notes") or "").strip() or None,
                )
            )
            imported_count += 1
        self.db.add(
            PortfolioLedgerImportModel(
                portfolio_id=portfolio_id,
                import_format=import_format,
                idempotency_key=idempotency_key,
                imported_count=imported_count,
                source_schema_version=source_document["schema_version"],
                source_document=source_document,
                source_sha256=source_sha256,
                source_as_of=source_as_of,
                source_currency=source_currency,
            )
        )
        await self.db.commit()
        imported = await self.db.scalar(
            select(PortfolioLedgerImportModel).where(
                PortfolioLedgerImportModel.portfolio_id == portfolio_id,
                PortfolioLedgerImportModel.idempotency_key == idempotency_key,
            )
        )
        if imported is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "PORTFOLIO_IMPORT_SOURCE_PERSISTENCE_FAILED"},
            )
        return {
            "duplicate": False,
            "imported_count": imported_count,
            "import_version_id": imported.id,
            "source_sha256": source_sha256,
            "source_material_status": "verified",
        }

    async def holdings(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        position_stats = self._build_position_stats(transactions)
        items = [
            {
                "symbol": symbol,
                "quantity": round(float(item["quantity"]), 6),
                "cost_basis": round(float(item["avg_cost"]), 6),
            }
            for symbol, item in position_stats.items()
            if abs(float(item["quantity"])) > 0
        ]
        return {"items": items, "total": len(items)}

    async def snapshots(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        derived_items = self._build_snapshot_items(transactions)
        snapshots = await self._list_snapshot_models(portfolio_id)
        items = [self._serialize_snapshot(item) for item in snapshots]
        if items != derived_items:
            await self._persist_snapshot_items(portfolio_id, derived_items)
            return {"items": derived_items, "total": len(derived_items)}
        return {"items": items, "total": len(items)}

    async def backfill_snapshots(
        self,
        user_id: str,
        portfolio_id: str,
    ) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        items = self._build_snapshot_items(transactions)
        await self._persist_snapshot_items(portfolio_id, items)
        return {"items": items, "total": len(items)}

    async def export_portfolio(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        return {
            "schema_version": "portfolio-ledger.v1",
            "portfolio": self._serialize_portfolio(
                portfolio,
                transaction_count=len(transactions),
            ),
            "transactions": [self._serialize_transaction(item) for item in transactions],
        }

    async def analytics_context(self, user_id: str, portfolio_id: str) -> dict[str, Any] | None:
        portfolio = await self._get_portfolio(user_id, portfolio_id)
        if portfolio is None:
            return None
        transactions = await self._list_transaction_models(portfolio_id)
        snapshot_items = self._build_snapshot_items(transactions)
        position_stats = self._build_position_stats(transactions)
        return {
            "portfolio": self._serialize_portfolio(
                portfolio,
                transaction_count=len(transactions),
            ),
            "equity_curve": [float(item["nav"]) for item in snapshot_items],
            "equity_dates": [str(item["date"]) for item in snapshot_items],
            "position_stats": position_stats,
            "transaction_count": len(transactions),
        }

    async def _get_portfolio(
        self,
        user_id: str,
        portfolio_id: str,
    ) -> PortfolioLedgerModel | None:
        result = await self.db.execute(
            select(PortfolioLedgerModel).where(
                PortfolioLedgerModel.id == portfolio_id,
                PortfolioLedgerModel.owner_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _list_transaction_models(
        self,
        portfolio_id: str,
    ) -> list[PortfolioLedgerTransactionModel]:
        result = await self.db.execute(
            select(PortfolioLedgerTransactionModel)
            .where(PortfolioLedgerTransactionModel.portfolio_id == portfolio_id)
            .order_by(
                PortfolioLedgerTransactionModel.trade_date,
                PortfolioLedgerTransactionModel.created_at,
            )
        )
        return list(result.scalars().all())

    async def _persist_snapshot_items(
        self,
        portfolio_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        await self.db.execute(
            delete(PortfolioLedgerSnapshotModel).where(
                PortfolioLedgerSnapshotModel.portfolio_id == portfolio_id
            )
        )
        for item in items:
            self.db.add(
                PortfolioLedgerSnapshotModel(
                    portfolio_id=portfolio_id,
                    snapshot_date=str(item["date"]),
                    snapshot_index=int(item["snapshot_index"]),
                    cash_flow=float(item["cash_flow"]),
                    nav=float(item["nav"]),
                )
            )
        await self.db.commit()

    def _build_position_stats(
        self,
        transactions: list[PortfolioLedgerTransactionModel],
    ) -> dict[str, dict[str, float]]:
        positions: dict[str, dict[str, float]] = {}
        for txn in transactions:
            trade_type = str(txn.trade_type or "")
            symbol = str(txn.symbol or "")
            if trade_type not in _POSITION_TRADE_TYPES or not symbol:
                continue
            state = positions.setdefault(
                symbol,
                {
                    "quantity": 0.0,
                    "avg_cost": 0.0,
                    "last_price": 0.0,
                    "market_value": 0.0,
                    "return_ratio": 0.0,
                },
            )
            quantity = float(txn.quantity)
            price = float(txn.price)
            previous_quantity = float(state["quantity"])
            previous_avg_cost = float(state["avg_cost"])
            if trade_type == "buy":
                new_quantity = previous_quantity + quantity
                total_cost = previous_quantity * previous_avg_cost + quantity * price
                state["quantity"] = new_quantity
                state["avg_cost"] = total_cost / new_quantity if abs(new_quantity) > 1e-12 else 0.0
            else:
                new_quantity = previous_quantity - quantity
                state["quantity"] = new_quantity
                if abs(new_quantity) <= 1e-12:
                    state["avg_cost"] = 0.0
                elif previous_quantity <= 0:
                    total_cost = abs(previous_quantity) * previous_avg_cost + quantity * price
                    state["avg_cost"] = total_cost / abs(new_quantity)
                elif previous_quantity > 0 and new_quantity < 0:
                    state["avg_cost"] = price
            state["last_price"] = price

        for state in positions.values():
            quantity = float(state["quantity"])
            last_price = float(state["last_price"])
            avg_cost = float(state["avg_cost"])
            state["market_value"] = quantity * last_price
            if avg_cost > 0 and last_price > 0 and abs(quantity) > 1e-12:
                direction = 1.0 if quantity >= 0 else -1.0
                state["return_ratio"] = ((last_price - avg_cost) / avg_cost) * direction
            else:
                state["return_ratio"] = 0.0
        return positions

    async def _transaction_count(self, portfolio_id: str) -> int:
        transactions = await self._list_transaction_models(portfolio_id)
        return len(transactions)

    async def _list_snapshot_models(
        self,
        portfolio_id: str,
    ) -> list[PortfolioLedgerSnapshotModel]:
        result = await self.db.execute(
            select(PortfolioLedgerSnapshotModel)
            .where(PortfolioLedgerSnapshotModel.portfolio_id == portfolio_id)
            .order_by(
                PortfolioLedgerSnapshotModel.snapshot_index,
                PortfolioLedgerSnapshotModel.snapshot_date,
            )
        )
        return list(result.scalars().all())

    def _build_snapshot_items(
        self,
        transactions: list[PortfolioLedgerTransactionModel],
    ) -> list[dict[str, Any]]:
        if not transactions:
            return [
                {
                    "date": str(date.today()),
                    "snapshot_index": 1,
                    "cash_flow": 0.0,
                    "nav": _BASE_NAV,
                }
            ]
        items: list[dict[str, Any]] = []
        cash_balance = _BASE_NAV
        positions: dict[str, dict[str, float]] = {}
        for index, txn in enumerate(transactions, start=1):
            signed_cash = self._signed_cash_flow(txn)
            cash_balance += signed_cash
            self._apply_transaction_to_positions(positions, txn)
            marked_value = sum(
                float(position["quantity"]) * float(position["last_price"])
                for position in positions.values()
            )
            items.append(
                {
                    "date": txn.trade_date,
                    "snapshot_index": index,
                    "cash_flow": round(signed_cash, 2),
                    "nav": round(cash_balance + marked_value, 2),
                }
            )
        return items

    def _apply_transaction_to_positions(
        self,
        positions: dict[str, dict[str, float]],
        transaction: PortfolioLedgerTransactionModel,
    ) -> None:
        trade_type = str(transaction.trade_type or "")
        symbol = str(transaction.symbol or "")
        if trade_type not in _POSITION_TRADE_TYPES or not symbol:
            return
        state = positions.setdefault(
            symbol,
            {"quantity": 0.0, "avg_cost": 0.0, "last_price": 0.0},
        )
        quantity = float(transaction.quantity)
        price = float(transaction.price)
        previous_quantity = float(state["quantity"])
        previous_avg_cost = float(state["avg_cost"])
        if trade_type == "buy":
            new_quantity = previous_quantity + quantity
            total_cost = previous_quantity * previous_avg_cost + quantity * price
            state["quantity"] = new_quantity
            state["avg_cost"] = total_cost / new_quantity if abs(new_quantity) > 1e-12 else 0.0
        else:
            new_quantity = previous_quantity - quantity
            state["quantity"] = new_quantity
            if abs(new_quantity) <= 1e-12:
                state["avg_cost"] = 0.0
            elif previous_quantity <= 0:
                total_cost = abs(previous_quantity) * previous_avg_cost + quantity * price
                state["avg_cost"] = total_cost / abs(new_quantity)
            elif previous_quantity > 0 and new_quantity < 0:
                state["avg_cost"] = price
        state["last_price"] = price

    def _signed_cash_flow(self, transaction: PortfolioLedgerTransactionModel) -> float:
        trade_type = str(transaction.trade_type or "").lower()
        if trade_type == "buy":
            return -abs(transaction.quantity * transaction.price)
        if trade_type == "sell":
            return abs(transaction.quantity * transaction.price)
        amount = float(transaction.amount or 0.0)
        if trade_type in {"dividend", "cash_deposit"}:
            return abs(amount)
        if trade_type in {"cash_withdrawal", "fee"}:
            return -abs(amount)
        return 0.0

    def _serialize_portfolio(
        self,
        portfolio: PortfolioLedgerModel,
        *,
        transaction_count: int,
    ) -> dict[str, Any]:
        return {
            "id": portfolio.id,
            "name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "source_type": portfolio.source_type,
            "benchmark_symbol": portfolio.benchmark_symbol,
            "tags": list(portfolio.tags or []),
            "notes": portfolio.notes,
            "transaction_count": transaction_count,
        }

    def _serialize_transaction(
        self,
        transaction: PortfolioLedgerTransactionModel,
    ) -> dict[str, Any]:
        return {
            "id": transaction.id,
            "symbol": transaction.symbol,
            "trade_type": transaction.trade_type,
            "quantity": transaction.quantity,
            "price": transaction.price,
            "amount": transaction.amount,
            "trade_date": transaction.trade_date,
            "benchmark_symbol": transaction.benchmark_symbol,
            "tags": list(transaction.tags or []),
            "notes": transaction.notes,
        }

    def _serialize_snapshot(self, snapshot: PortfolioLedgerSnapshotModel) -> dict[str, Any]:
        return {
            "date": snapshot.snapshot_date,
            "snapshot_index": snapshot.snapshot_index,
            "cash_flow": snapshot.cash_flow,
            "nav": snapshot.nav,
        }

    def _normalize_tags(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]


def get_portfolio_ledger_service(db: AsyncSession) -> PortfolioLedgerService:
    return PortfolioLedgerService(db)


def _import_material_status(imported: PortfolioLedgerImportModel) -> str:
    if imported.source_document is None or imported.source_sha256 is None:
        return "unavailable_legacy"
    if verify_portfolio_import_source(
        document=imported.source_document,
        expected_sha256=imported.source_sha256,
        expected_schema_version=imported.source_schema_version,
        import_format=imported.import_format,
        imported_count=imported.imported_count,
        source_as_of=imported.source_as_of,
        source_currency=imported.source_currency,
    ):
        return "verified"
    return "integrity_invalid"
