from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models.approved_target_http_operation import ApprovedTargetHttpOperation
from app.models.legacy_paper_import import LegacyPaperImportReceipt
from app.models.paper_runtime import PaperEquitySnapshot
from app.models.paper_trading import Account, Order, PaperTrade, Position
from app.models.service_order_operation import ServiceOrderOperation
from app.models.strategy_target_approval import (
    StrategyTargetApproval,
    StrategyTargetApprovalEvent,
)
from app.models.strategy_version import StrategyVersion
from app.models.user import User
from app.models.workspace import StrategyUnit, Workspace
from app.services.mig03_boundary_inventory import (
    AfiBoundarySnapshot,
    AfiMigrationBoundaryError,
    assert_afi_state_conserved,
    capture_afi_boundary,
    enumerate_paper_snapshot_writers,
)

_USER_ID = "mig03-inventory-user"
_WORKSPACE_ID = "mig03-inventory-workspace"
_UNIT_ID = "mig03-inventory-unit"
_INSTANCE_ID = "mig03-inventory-instance"
_ACCOUNT_ID = "mig03-inventory-account"
_CONFIGURATION_SHA256 = "a" * 64


def _database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(
            engine,
            tables=(
                User.__table__,
                Workspace.__table__,
                StrategyUnit.__table__,
                Account.__table__,
                Position.__table__,
                Order.__table__,
                PaperTrade.__table__,
                PaperEquitySnapshot.__table__,
                ServiceOrderOperation.__table__,
                ApprovedTargetHttpOperation.__table__,
                StrategyTargetApproval.__table__,
                StrategyTargetApprovalEvent.__table__,
                StrategyVersion.__table__,
                LegacyPaperImportReceipt.__table__,
            ),
        )
        with Session(engine) as session:
            session.add(
                User(
                    id=_USER_ID,
                    username="mig03-inventory-user",
                    email="mig03-inventory@example.test",
                    hashed_password="synthetic-test-only-unused",
                )
            )
            session.add(
                Workspace(
                    id=_WORKSPACE_ID,
                    user_id=_USER_ID,
                    name="MIG03 configured paper runtime",
                    workspace_type="trading",
                    settings={},
                    trading_config={"source": "synthetic"},
                )
            )
            session.add(
                StrategyUnit(
                    id=_UNIT_ID,
                    workspace_id=_WORKSPACE_ID,
                    strategy_id="mig03-inventory-strategy",
                    strategy_name="MIG03 configured paper runtime",
                    symbol="SYNTH-USD",
                    trading_mode="paper",
                    trading_instance_id=_INSTANCE_ID,
                    run_status="running",
                    lock_running=False,
                    trading_snapshot={"position_pnl": 1.25},
                    metrics_snapshot={"final_value": 100001.25},
                    unit_settings={"initial_cash": 100000.0},
                )
            )
            session.add(
                Account(
                    id=_ACCOUNT_ID,
                    user_id=_USER_ID,
                    name="MIG03 persisted account FK",
                    initial_cash=100000.0,
                    current_cash=99988.75,
                    total_equity=100001.25,
                )
            )
            session.add(
                PaperEquitySnapshot(
                    id="mig03-inventory-snapshot",
                    user_id=_USER_ID,
                    workspace_id=_WORKSPACE_ID,
                    unit_id=_UNIT_ID,
                    instance_id=_INSTANCE_ID,
                    paper_account_id=_ACCOUNT_ID,
                    observed_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
                    source="migration_seed",
                    total_equity=100001.25,
                    cash=99988.75,
                    position_value=12.5,
                    unrealized_pnl=1.25,
                    realized_pnl=0.0,
                    metadata_json={"seed": "synthetic"},
                )
            )
            session.commit()
    finally:
        engine.dispose()


def test_configured_snapshot_writer_uses_persisted_fk_and_exact_manifest(
    tmp_path: Path,
) -> None:
    database = tmp_path / "afi-snapshot-inventory.sqlite3"
    _database(database)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            rows = enumerate_paper_snapshot_writers(
                session,
                account_refs_by_paper_account={_ACCOUNT_ID: "typed-target-account-ref"},
                configuration_sha256=_CONFIGURATION_SHA256,
            )
        assert len(rows) == 1
        writer = rows[0]
        assert writer.consumer_kind == "afi_snapshot_scheduler"
        assert writer.account_ref == "typed-target-account-ref"
        assert writer.paper_account_id == _ACCOUNT_ID
        assert (writer.user_id, writer.workspace_id, writer.unit_id, writer.instance_id) == (
            _USER_ID,
            _WORKSPACE_ID,
            _UNIT_ID,
            _INSTANCE_ID,
        )
        assert writer.consumer_id.startswith("afi-snapshot-writer-v1:")
        assert len(writer.configuration_sha256) == 64
        assert len(writer.scope_sha256) == 64
        assert len(writer.operations_sha256) == 64
        with Session(engine) as session:
            with pytest.raises(AfiMigrationBoundaryError) as extra_mapping:
                enumerate_paper_snapshot_writers(
                    session,
                    account_refs_by_paper_account={
                        _ACCOUNT_ID: "typed-target-account-ref",
                        "unobserved-account": "unobserved-target-account-ref",
                    },
                    configuration_sha256=_CONFIGURATION_SHA256,
                )
        assert extra_mapping.value.code == "AFI_MIG03_INVALID_BOUNDARY_SCOPE"
    finally:
        engine.dispose()


def test_afi_boundary_capture_returns_all_public_projections(tmp_path: Path) -> None:
    database = tmp_path / "afi-boundary-projection.sqlite3"
    _database(database)
    account_ref = "typed-target-account-ref"
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            before = capture_afi_boundary(
                session,
                scope_ref="mig03-afi-inventory-scope",
                account_ref=account_ref,
                strategy_refs=("mig03-inventory-strategy",),
                account_paper_accounts={account_ref: _ACCOUNT_ID},
                paper_account_instances={_ACCOUNT_ID: _INSTANCE_ID},
                source_ref=str(database.resolve()),
                configuration_sha256=_CONFIGURATION_SHA256,
            )
        with Session(engine) as session:
            after = capture_afi_boundary(
                session,
                scope_ref="mig03-afi-inventory-scope",
                account_ref=account_ref,
                strategy_refs=("mig03-inventory-strategy",),
                account_paper_accounts={account_ref: _ACCOUNT_ID},
                paper_account_instances={_ACCOUNT_ID: _INSTANCE_ID},
                source_ref=str(database.resolve()),
                configuration_sha256=_CONFIGURATION_SHA256,
            )
        assert type(before) is AfiBoundarySnapshot
        assert type(after) is AfiBoundarySnapshot
        participants = before.boundary_participants()
        assert tuple(item["participant_id"] for item in participants) == (
            "afi_operations",
            "afi_paper",
        )
        assert tuple(item["row_count"] for item in participants) == (0, 2)
        assert all(item["configuration_sha256"] == _CONFIGURATION_SHA256 for item in participants)
        assert before.identity_links == (
            (
                "paper_account",
                _ACCOUNT_ID,
                "paper_user",
                _USER_ID,
            ),
            (
                "paper_account_ref",
                account_ref,
                "paper_account",
                _ACCOUNT_ID,
            ),
            (
                "paper_equity_snapshot",
                "mig03-inventory-snapshot",
                "paper_account",
                _ACCOUNT_ID,
            ),
            (
                "paper_equity_snapshot",
                "mig03-inventory-snapshot",
                "paper_instance",
                _INSTANCE_ID,
            ),
        )
        amounts = dict(before.amounts)
        assert amounts["account:mig03-inventory-account:initial_cash"] == "100000"
        assert amounts["account:mig03-inventory-account:current_cash"] == "99988.75"
        assert amounts["equity_snapshot:mig03-inventory-snapshot:cash"] == "99988.75"
        assert before.positions == ()
        assert before.unresolved_ids == ()
        assert before.reservation_ids == ()
        assert_afi_state_conserved(before, after)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "snapshot_account_id",
    [None, "another-account"],
)
def test_configured_snapshot_writer_rejects_unbound_or_conflicting_history(
    tmp_path: Path,
    snapshot_account_id: str | None,
) -> None:
    database = tmp_path / "afi-snapshot-inventory-invalid.sqlite3"
    _database(database)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            snapshot = session.get(PaperEquitySnapshot, "mig03-inventory-snapshot")
            assert snapshot is not None
            snapshot.paper_account_id = snapshot_account_id
            if snapshot_account_id == "another-account":
                session.add(
                    Account(
                        id="another-account",
                        user_id=_USER_ID,
                        name="Conflicting persisted account",
                    )
                )
            session.commit()
        with Session(engine) as session:
            with pytest.raises(AfiMigrationBoundaryError) as invalid:
                enumerate_paper_snapshot_writers(
                    session,
                    account_refs_by_paper_account={_ACCOUNT_ID: "typed-target-account-ref"},
                    configuration_sha256=_CONFIGURATION_SHA256,
                )
        assert invalid.value.code == "AFI_MIG03_INVALID_BOUNDARY_SCOPE"
    finally:
        engine.dispose()
