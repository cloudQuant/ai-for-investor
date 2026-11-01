"""Focused compatibility tests for SDK account-book financial projections."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from decimal import Decimal

import pytest
from pydantic_settings import BaseSettings

_ORIGINAL_ENV = os.environ
_ORIGINAL_SETTINGS_INIT = BaseSettings.__init__
_SYNTHETIC_SETTINGS_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "afi-account-book-contract-synthetic-secret-0123456789",
    "ADMIN_PASSWORD": "AFI-Synthetic-Admin-Password-98765",
    "JWT_SECRET_KEY": "afi-account-book-contract-synthetic-jwt-0123456789",
    "JWT_ALGORITHM": "HS256",
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": tempfile.mkdtemp(prefix="afi_account_book_contract_logs_"),
    "BT_API_LOG_DIR": tempfile.mkdtemp(prefix="afi_account_book_contract_sdk_logs_"),
    "SQL_ECHO": "false",
    "AI_CHAT_ENABLED": "false",
    "AI_CHAT_BASE_URL": "",
    "AI_CHAT_API_KEY": "",
    "AI_CHAT_MODEL": "",
}


def _settings_init_without_dotenv(self, *args, **kwargs):
    kwargs["_env_file"] = None
    _ORIGINAL_SETTINGS_INIT(self, *args, **kwargs)


BaseSettings.__init__ = _settings_init_without_dotenv
os.environ = dict(_SYNTHETIC_SETTINGS_ENV)  # noqa: B003 - avoid developer .env/provider inputs
try:
    from app.services.service_read.client import (
        AccountBookBinding,
        AuthorizedServiceReadClient,
        ServiceReadUnavailableError,
    )
    from app.services.service_read.contracts import AccountBookReadView, ServiceReadContractError
finally:
    BaseSettings.__init__ = _ORIGINAL_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore process environment exactly


_ACCOUNT_REF = "afi-account-book-contract-account"
_ACCOUNT_KEY = "synthetic-execution-account-key"
_JOURNAL_GENERATION = "synthetic-execution-journal-generation"
_CURRENT_CURSOR = 7
_PINNED_SDK_MODULES = {
    "bt_api_py.service_execution_account_books": "b69e21212d8b92ebe35e5f179be44bce82e59fd7beb45164353de46663da1d07",
    "bt_api_execution.account_financial_ledger": "122ebabac60d5b6b1bac7ff4ca49aad62a73ab27045567fc5a7e6633c079322f",
    "bt_api_execution.account_reconciliation": "6a325700ee18654b4cc63c3ff855e86979b249fb372d9e527a9aef5cea9a70db",
    "bt_api_execution.contracts": "842a0bc6a6c2b6d1267fa8d875c14ac2f7a65dcffccf6a6ae742d719e8893394",
    "bt_api_execution.store": "f0763053686ba01ed91ad1052dea2fe73e59da1e963a1f96a22d794e5055a70a",
    "bt_api_base.service_protocol": "ef31a048e95785c5128f6cbc9e202b939955d2f845c5680ecf2d8a8e28421b87",
    "bt_api_base.account_protocol": "aaae92cc6a99a328398cefe670ccf223e6ec3ba4c4fef51afb0b1323c4021774",
}
_PINNED_SDK_MODULE_ROOTS = {
    "bt_api_py.service_execution_account_books": "AFI_SDK115_ROOT_SRC",
    "bt_api_execution.account_financial_ledger": "AFI_SDK115_EXECUTION_SRC",
    "bt_api_execution.account_reconciliation": "AFI_SDK115_EXECUTION_SRC",
    "bt_api_execution.contracts": "AFI_SDK115_EXECUTION_SRC",
    "bt_api_execution.store": "AFI_SDK115_EXECUTION_SRC",
    "bt_api_base.service_protocol": "AFI_SDK115_BASE_SRC",
    "bt_api_base.account_protocol": "AFI_SDK115_BASE_SRC",
}


def _assert_pinned_sdk_sources():
    import importlib
    from pathlib import Path

    for module_name, expected_sha256 in _PINNED_SDK_MODULES.items():
        module = importlib.import_module(module_name)
        source_path = Path(module.__file__).resolve()
        actual_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256, module_name
        root_variable = _PINNED_SDK_MODULE_ROOTS[module_name]
        expected_root = os.environ.get(root_variable)
        if expected_root is not None:
            assert source_path.is_relative_to(Path(expected_root).resolve()), module_name


class _Runtime:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def call(self, mount, operation, arguments, scope_ref=None):
        self.calls.append((mount, operation, dict(arguments), scope_ref))
        return self.payload


def _account_projection():
    return {
        "view": "ACCOUNT",
        "coverage": {
            "account_key": _ACCOUNT_KEY,
            "scope_directory_revision": "synthetic-scope-directory-r1",
            "journal_generation": _JOURNAL_GENERATION,
            "baseline_execution_cursor": 0,
            "current_execution_cursor": _CURRENT_CURSOR,
            "complete": True,
            "reasons": [],
            "scanned_outbox_events": _CURRENT_CURSOR,
            "outbox_history_contiguous": True,
            "outbox_scan_complete": True,
            "continuations": [],
            "input_continuations": [],
            "quarantined_intents": [],
        },
        "state": "BALANCED",
        "books": [],
        "managed_orders": [],
        "managed_fills": [],
        "external_orders": [],
        "external_fills": [],
        "provider_position_change": [],
        "position_residual": [],
        "fee_residual": [],
    }


def _sdk_financial_projection():
    """Build the SDK's canonical JSON shape from its financial wire dataclasses."""

    _assert_pinned_sdk_sources()

    from bt_api_execution import (
        AccountFinancialProjectionV1,
        CurrencyAmountV1,
        FinancialCostMethod,
        FinancialLedgerCutV1,
        FinancialOwnerKind,
        FinancialOwnerV1,
        FinancialProductModel,
        FinancialSourceKind,
        FinancialWatermarkV1,
        OwnerFinancialBookV1,
        OwnerPositionCostV1,
    )
    from bt_api_py.service_execution_account_books import _json_value

    captured_at_ns = 100
    ledger_cut = FinancialLedgerCutV1(
        account_key=_ACCOUNT_KEY,
        owner_directory_revision="synthetic-financial-owner-directory-r1",
        captured_at_ns=captured_at_ns,
        watermarks=(
            FinancialWatermarkV1(
                FinancialSourceKind.EXECUTION_OUTBOX,
                "sqlite-execution-outbox",
                _JOURNAL_GENERATION,
                _CURRENT_CURSOR,
                captured_at_ns,
            ),
            FinancialWatermarkV1(
                FinancialSourceKind.ACCOUNT_FACTS,
                "synthetic-account-facts",
                "synthetic-account-facts-generation",
                3,
                captured_at_ns,
            ),
            FinancialWatermarkV1(
                FinancialSourceKind.ACCOUNT_ACTIVITY,
                "synthetic-account-activity",
                "synthetic-account-activity-generation",
                4,
                captured_at_ns,
            ),
        ),
    )
    owner = FinancialOwnerV1(
        FinancialOwnerKind.STRATEGY,
        "strategy-contract-test",
        "synthetic-execution-scope-key",
    )
    book = OwnerFinancialBookV1(
        owner=owner,
        ledger_cut=ledger_cut,
        cash=(CurrencyAmountV1("USD", Decimal("1000")),),
        positions=(
            OwnerPositionCostV1(
                "BTC-USD",
                Decimal("2"),
                Decimal("40000"),
                "USD",
                FinancialCostMethod.AVERAGE_COST,
                FinancialProductModel.SPOT,
                "v1",
            ),
        ),
        cumulative_fees=(CurrencyAmountV1("USD", Decimal("0.25")),),
        realized_pnl=(CurrencyAmountV1("USD", Decimal("12.5")),),
        cost_basis_complete=True,
    )
    account_projection = AccountFinancialProjectionV1(
        cut=ledger_cut,
        books=(book,),
        unallocated_cash_residual=(CurrencyAmountV1("USD", Decimal("25")),),
        unallocated_position_residual=(("BTC-USD", Decimal("0.5")),),
        unallocated_fee_residual=(CurrencyAmountV1("USD", Decimal("0.05")),),
        complete=True,
        state="RESIDUAL",
    )
    return _json_value(
        {
            "available": True,
            "source": "PERSISTED_EXECUTION_FINANCIAL_PROJECTION",
            "freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED",
            "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
            "complete": True,
            "ledger_cut": account_projection.cut,
            "state": account_projection.state,
            "books": account_projection.books,
            "unallocated": {
                "cash": account_projection.unallocated_cash_residual,
                "positions": account_projection.unallocated_position_residual,
                "fees": account_projection.unallocated_fee_residual,
            },
        }
    )


def _sdk_service_account_payload(tmp_path):
    """Call the pinned SDK service handler with deterministic synthetic facts."""

    _assert_pinned_sdk_sources()

    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_execution import (
        AllocationOwnerKind,
        ExecutionAccountSnapshot,
        ExecutionAllocationBaseline,
        ExecutionOwnerScope,
        ExecutionScope,
        ExecutionScopeDirectory,
        ExternalActivitySnapshot,
        SqliteExecutionStore,
    )
    from bt_api_py.service_execution_account_books import (
        ACCOUNT_BOOKS_QUERY_OPERATION,
        ExecutionAccountBookReadInputsV1,
        ExecutionOrderEntryService,
    )

    domain = "paper:afi-account-book-contract"
    strategy_ref = "strategy-contract-test"
    principal_ref = "afi-account-book-contract-reader"
    execution_scope = ExecutionScope("PAPER", "simulation", _ACCOUNT_REF, strategy_ref)
    wire_strategy_scope = WireScope(domain, account_ref=_ACCOUNT_REF, strategy_ref=strategy_ref)
    wire_account_scope = WireScope(domain, account_ref=_ACCOUNT_REF)
    identity = WireIdentity(WireRole.APPLICATION_CLIENT, principal_ref, "afi-contract-test-app")
    store = SqliteExecutionStore(str(tmp_path / "afi-account-book-contract.sqlite3"))

    class _Source:
        def authorize_account_view(self, *, principal_ref, identity, scope, account_key) -> bool:
            return (
                principal_ref == principal_ref_expected
                and identity == identity_expected
                and scope == account_scope_expected
                and account_key == account_key_expected
            )

        def read_inputs(self, *, account_key, journal_generation, execution_cursor):
            now_ns = time.time_ns()
            baseline_ns = now_ns - 10_000
            if account_key != account_key_expected:
                raise AssertionError("SDK requested an unbound account key")
            directory = ExecutionScopeDirectory(
                account_key=account_key,
                source="synthetic-trusted-owner-registry",
                source_ref="afi-account-book-contract-source-r1",
                revision="afi-account-book-contract-directory-r1",
                covers_from_ns=baseline_ns,
                as_of_ns=now_ns,
                scopes=(
                    ExecutionOwnerScope(
                        execution_scope,
                        AllocationOwnerKind.STRATEGY,
                        strategy_ref,
                        wire_strategy_scope,
                    ),
                ),
            )
            baseline = ExecutionAccountSnapshot(
                account_key=account_key,
                source="synthetic-account-snapshot",
                source_ref="afi-account-book-baseline-r1",
                generation="synthetic-provider-generation-r1",
                journal_generation=journal_generation,
                as_of_ns=baseline_ns,
                execution_cursor=0,
                position_mode="NET",
                positions=(),
                cumulative_fees=(),
                fee_coverage_start_ns=baseline_ns,
            )
            current = ExecutionAccountSnapshot(
                account_key=account_key,
                source="synthetic-account-snapshot",
                source_ref="afi-account-book-current-r1",
                generation="synthetic-provider-generation-r1",
                journal_generation=journal_generation,
                as_of_ns=now_ns,
                execution_cursor=execution_cursor,
                position_mode="NET",
                positions=(),
                cumulative_fees=(),
                fee_coverage_start_ns=baseline_ns,
            )
            allocation = ExecutionAllocationBaseline(
                account_key=account_key,
                source="synthetic-owner-baseline",
                source_ref="afi-account-book-owner-baseline-r1",
                revision="afi-account-book-owner-baseline-revision-r1",
                scope_directory_revision=directory.revision,
                provider_generation="synthetic-provider-generation-r1",
                journal_generation=journal_generation,
                as_of_ns=baseline_ns,
                execution_cursor=0,
                positions=(),
            )
            activity = ExternalActivitySnapshot(
                account_key=account_key,
                source="synthetic-account-activity",
                source_ref="afi-account-book-activity-r1",
                generation="synthetic-provider-generation-r1",
                coverage_start_ns=baseline_ns,
                coverage_end_ns=now_ns,
                fills=(),
                orders=(),
            )
            return ExecutionAccountBookReadInputsV1(
                directory, baseline, current, allocation, activity
            )

    class _Dispatch:
        def submit(self, intent):
            raise AssertionError("read-only contract test must not dispatch orders")

        def cancel(self, intent):
            raise AssertionError("read-only contract test must not dispatch cancellations")

    account_key_expected = execution_scope.account_key
    principal_ref_expected = principal_ref
    identity_expected = identity
    account_scope_expected = wire_account_scope
    service = ExecutionOrderEntryService(
        store,
        {wire_strategy_scope: execution_scope},
        dispatch=_Dispatch(),
        allow_unprotected=True,
        writer_id="afi-account-book-contract-test",
        account_books_source=_Source(),
    )
    try:
        response = service.handle(
            ACCOUNT_BOOKS_QUERY_OPERATION,
            principal_ref=principal_ref,
            identity=identity,
            scope=wire_account_scope,
            arguments={},
        )
        assert response["ok"] is True and response["code"] == "OK"
        return response
    finally:
        store.close()


def test_legacy_account_book_shape_remains_accepted_and_unknown_fields_fail_closed():
    view = AccountBookReadView("account-ref", "account-key-id", _account_projection())
    assert "financial" not in view.to_dict()

    unknown = _account_projection()
    unknown["account_total"] = "100"
    with pytest.raises(ServiceReadContractError) as error:
        AccountBookReadView("account-ref", "account-key-id", unknown)
    assert error.value.code == "INVALID_ACCOUNT_BOOK_REPLY"


def test_sdk_financial_extension_is_frozen_but_not_promoted_to_account_total():
    projection = _account_projection()
    projection["financial"] = _sdk_financial_projection()
    view = AccountBookReadView("account-ref", "account-key-id", projection)

    frozen_financial = view.projection["financial"]
    assert frozen_financial["available"] is True
    assert frozen_financial["books"][0]["owner"]["kind"] == "STRATEGY"
    assert frozen_financial["ledger_cut"]["account_key"] == _ACCOUNT_KEY
    assert frozen_financial["books"][0]["cash"] == ({"currency": "USD", "amount": "1000"},)
    assert frozen_financial["unallocated"]["cash"] == ({"currency": "USD", "amount": "25"},)
    assert not {"cash", "equity", "account_total", "valuation"} & set(view.projection)
    assert view.to_dict()["financial"]["cut_relationship"] == (
        "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
    )


def test_legacy_partial_reason_and_financial_residual_keep_separate_state_cuts():
    projection = _account_projection()
    projection["state"] = "PARTIAL"
    projection["coverage"]["complete"] = False
    projection["coverage"]["reasons"] = ["OUTBOX_GAP"]
    projection["position_residual"] = [{"instrument": "BTC-USD", "net_quantity": "0.5"}]
    projection["financial"] = _sdk_financial_projection()

    view = AccountBookReadView("account-ref", "account-key-id", projection)

    assert view.projection["state"] == "PARTIAL"
    assert view.projection["coverage"]["reasons"] == ("OUTBOX_GAP",)
    assert view.projection["financial"]["state"] == "RESIDUAL"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-financial-key",
        "missing-financial-field",
        "invalid-availability-envelope",
        "wrong-account-key",
        "wrong-execution-generation",
        "wrong-execution-cursor",
        "duplicate-owner",
        "owner-cut-mismatch",
        "balanced-with-residual",
        "residual-without-residual",
    ],
)
def test_financial_extension_rejects_malformed_or_cross_account_cut_data(mutation):
    projection = _account_projection()
    financial = _sdk_financial_projection()
    if mutation == "unknown-financial-key":
        financial["owner_cash_total"] = "999"
    elif mutation == "missing-financial-field":
        del financial["source"]
    elif mutation == "invalid-availability-envelope":
        financial["available"] = False
        financial["ledger_cut"] = {}
    elif mutation == "wrong-account-key":
        financial["ledger_cut"]["account_key"] = "another-account-key"
    elif mutation == "wrong-execution-generation":
        financial["ledger_cut"]["watermarks"][0]["generation"] = "another-journal"
    elif mutation == "wrong-execution-cursor":
        financial["ledger_cut"]["watermarks"][0]["cursor"] = _CURRENT_CURSOR - 1
    elif mutation == "duplicate-owner":
        financial["books"].append(dict(financial["books"][0]))
    elif mutation == "owner-cut-mismatch":
        financial["books"][0]["ledger_cut"]["owner_directory_revision"] = "different-cut"
    elif mutation == "balanced-with-residual":
        financial["state"] = "BALANCED"
    elif mutation == "residual-without-residual":
        financial["state"] = "RESIDUAL"
        financial["unallocated"] = {"cash": [], "positions": [], "fees": []}
    projection["financial"] = financial

    with pytest.raises(ServiceReadContractError) as error:
        AccountBookReadView("account-ref", "account-key-id", projection)
    assert error.value.code == "INVALID_ACCOUNT_BOOK_FINANCIAL"


def test_actual_sdk_service_handle_payload_flows_through_afi_read_client(tmp_path):
    from bt_api_base.account_protocol import AccountKey

    sdk_response = _sdk_service_account_payload(tmp_path)
    account_key = AccountKey(
        provider="synthetic-provider",
        venue="synthetic-venue",
        environment="paper",
        account_id=_ACCOUNT_REF,
    )
    runtime = _Runtime(sdk_response)
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        account_book_bindings={
            _ACCOUNT_REF: AccountBookBinding(
                "application.account_books",
                "account-book-contract-scope-v1",
                account_key,
            )
        },
    )

    view = client.read_account_book(_ACCOUNT_REF)

    assert view.projection["financial"] == {
        "available": False,
        "code": "FINANCIAL_DIRECTORY_UNAVAILABLE",
        "freshness": "NOT_ESTABLISHED",
        "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
    }
    assert runtime.calls == [
        (
            "application.account_books",
            "execution.account_books.query",
            {},
            "account-book-contract-scope-v1",
        )
    ]


def test_account_book_client_rejects_malformed_sdk_financial_extension():
    response = {"ok": True, "code": "OK", "result": _account_projection()}
    response["result"]["financial"] = {
        "available": False,
        "code": "UNKNOWN_FINANCIAL_CODE",
        "freshness": "NOT_ESTABLISHED",
        "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
    }
    account_key = type("_AccountKey", (), {"account_key_id": "account-key-id"})()
    client = AuthorizedServiceReadClient(
        _Runtime(response),
        account_bindings={},
        account_book_bindings={
            _ACCOUNT_REF: AccountBookBinding(
                "application.account_books", "account-book-contract-scope-v1", account_key
            )
        },
    )
    with pytest.raises(ServiceReadUnavailableError, match="INVALID_ACCOUNT_BOOK_FINANCIAL"):
        client.read_account_book(_ACCOUNT_REF)
