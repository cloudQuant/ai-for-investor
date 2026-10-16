import threading
from types import SimpleNamespace

from app.services.quote.cache import match_cached_tick
from app.services.quote_service import QuoteService


def test_get_default_symbols_for_mt5_prefers_major_fx_and_avoids_indices_and_oil(monkeypatch):
    QuoteService._instance = None
    service = QuoteService()

    monkeypatch.setattr(service, "_get_live_trading_manager", lambda: None)

    symbols = [item["symbol"] for item in service._get_default_symbols_for_source("MT5")]

    assert "EURUSD" in symbols
    assert "GBPUSD" in symbols
    assert "USDJPY" in symbols
    assert "XAUUSD" in symbols
    assert "US30" not in symbols
    assert "NAS100" not in symbols
    assert "USOIL" not in symbols


def test_get_source_categories_uses_full_configured_catalog_not_live_tick_subset():
    QuoteService._instance = None
    service = QuoteService()

    categories = service.get_source_categories("CTP")

    assert {"股指期货", "贵金属", "有色金属", "黑色系", "农产品"}.issubset(categories)


def test_match_cached_tick_returns_exact_symbol_match():
    payload = {"symbol": "EURUSD", "bid_price": 1.1}
    cached = {"EURUSD": payload}

    result = match_cached_tick(cached, "EURUSD")

    assert result == payload


def test_remove_subscription_hides_default_and_add_restores_it(monkeypatch):
    QuoteService._instance = None
    service = QuoteService()
    service._custom_symbols = {"user-1": {"MT5": ["EURUSD"]}}
    service._hidden_subscriptions = {}

    monkeypatch.setattr("app.services.quote_service.save_custom_symbols", lambda data: None)
    monkeypatch.setattr("app.services.quote_service.save_hidden_subscriptions", lambda data: None)

    remaining = service.remove_subscriptions("mt5", "user-1", ["EURUSD", "GBPUSD"])

    assert remaining == []
    assert service._hidden_symbol_set("MT5", "user-1") == {"EURUSD", "GBPUSD"}

    service.add_custom_symbols("MT5", "user-1", ["EURUSD"])

    assert service._hidden_symbol_set("MT5", "user-1") == {"GBPUSD"}


def test_quote_reads_do_not_start_or_probe_legacy_gateway(monkeypatch):
    QuoteService._instance = None
    service = QuoteService()
    calls = []

    def fail_connect(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("quote reads must not connect a gateway")

    manager = SimpleNamespace(_gateways={}, connect_gateway=fail_connect)

    from app.services.live_trading import manager as live_manager

    def fail_manager_creation():
        raise AssertionError("quote reads must not create the legacy manager")

    monkeypatch.setattr(live_manager, "get_live_trading_manager", fail_manager_creation)
    monkeypatch.setattr(live_manager, "get_existing_live_trading_manager", lambda: manager)
    monkeypatch.setattr(service, "_get_running_workspace_context", lambda *args, **kwargs: {})

    sources = service.get_data_sources("user-1")
    quotes = service.get_quotes("MT5", "user-1", symbols=[])

    mt5 = next(item for item in sources if item["source"] == "MT5")
    assert mt5["status"] == "unavailable"
    assert mt5["status_message"] == "UNSUPPORTED_CAPABILITY"
    assert quotes["ticks"] == []
    assert calls == []
    assert not hasattr(service, "_send_gateway_command")

def test_running_workspace_context_skips_stale_gateway_mapping():
    QuoteService._instance = None
    service = QuoteService()
    manager = SimpleNamespace(
        _gateways={},
        _instance_gateways={"instance-stale": "missing-gateway"},
        list_instances=lambda user_id: [
            {
                "id": "instance-stale",
                "status": "running",
                "params": {
                    "symbol": "AAPL",
                    "workspace_unit": {"workspace_id": "workspace-1"},
                },
            }
        ],
    )

    context = service._get_running_workspace_context(manager, "user-1")

    assert context == {}


def test_source_gateway_states_ignores_null_or_malformed_workspace_state():
    QuoteService._instance = None
    service = QuoteService()

    states = service._get_source_gateway_states(
        None,
        "IB_WEB",
        {
            "null-gateway": {"state": None},
            "malformed-gateway": {"state": []},
        },
    )

    assert states == {}


def test_unconfigured_workspace_source_is_visible_but_quote_fails_closed(monkeypatch):
    QuoteService._instance = None
    service = QuoteService()
    state = {
        "config": SimpleNamespace(command_endpoint="tcp://127.0.0.1:5555"),
        "exchange_type": "CTP",
        "instances": {"instance-ctp"},
        "manual": False,
    }
    manager = SimpleNamespace(
        _gateway_lock=threading.RLock(),
        _gateways={"ctp-workspace-gateway": state},
        _instance_gateways={"instance-ctp": "ctp-workspace-gateway"},
        list_instances=lambda user_id: [
            {
                "id": "instance-ctp",
                "status": "running",
                "params": {
                    "symbol": "RB2510",
                    "workspace_unit": {"workspace_id": "workspace-ctp"},
                },
            },
        ],
    )
    monkeypatch.setattr(service, "_get_live_trading_manager", lambda: manager)
    monkeypatch.setattr(service, "_get_default_symbols_for_source", lambda _source: [])

    sources = service.get_data_sources("user-1", {"workspace-ctp": "CTP 工作区"})
    ctp = next(item for item in sources if item["source"] == "CTP")
    result = service.get_quotes("CTP", user_id="user-1", symbols=[])

    assert ctp["status"] == "unavailable"
    assert ctp["status_message"] == "UNSUPPORTED_CAPABILITY"
    assert ctp["gateway_count"] == 1
    assert ctp["workspace_count"] == 1
    assert ctp["running_symbol_count"] == 1
    assert ctp["workspaces"][0]["symbols"] == ["RB2510"]
    assert result["total"] == 1
    tick = result["ticks"][0]
    assert tick["symbol"] == "RB2510"
    assert tick["status"] == "error"
    assert tick["error_message"] == "UNSUPPORTED_CAPABILITY"
    assert tick["workspace_ids"] == ["workspace-ctp"]
    assert tick["workspace_names"] == ["workspace-ctp"]
    assert service._receivers == {}
    assert not hasattr(service, "_subscribe_symbols_on_gateway")

def test_unconfigured_custom_symbol_is_saved_without_gateway_subscription(monkeypatch):
    QuoteService._instance = None
    service = QuoteService()
    service._custom_symbols = {"user-1": {}}
    monkeypatch.setattr("app.services.quote_service.save_custom_symbols", lambda data: None)
    monkeypatch.setattr(service, "_get_live_trading_manager", lambda: None)

    assert service.add_custom_symbols("CTP", "user-1", ["RB2510"]) == ["RB2510"]
    result = service.get_quotes("CTP", "user-1", ["RB2510"])

    assert result["total"] == 1
    assert result["ticks"][0]["error_message"] == "UNSUPPORTED_CAPABILITY"
    assert service._receivers == {}
    assert not hasattr(service, "_subscribe_symbols_on_gateway")
