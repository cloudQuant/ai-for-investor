"""The collection scripts' entry-point contract, and the driver resolution that depends on it.

`AkshareToMySql.run` exists because 831 of the 1057 collection scripts end with
`script = SomeScript(); script.run()` while no class in their MRO defined `run`: the call only
ever worked inside the scheduler, which resolves `fetch_data` itself. These tests pin both halves
- the delegation, and the fact that the base grew no runtime `fetch_data` that would let the
driver mis-route a script whose only entry point is its own `run`.
"""

from __future__ import annotations

import types

import pandas as pd
import pytest

from app.data_fetch.configs.db_config import DB_CONFIG
from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql
from app.services.akshare.script import AkshareScriptService


class _FetchOnly(AkshareToMySql):
    def __init__(self) -> None:
        super().__init__(DB_CONFIG)
        self.seen: dict[str, object] | None = None

    def fetch_data(self, **kwargs: object) -> pd.DataFrame:
        self.seen = kwargs
        return pd.DataFrame({"value": [1]})


class _OwnRun(AkshareToMySql):
    def __init__(self) -> None:
        super().__init__(DB_CONFIG)

    def run(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame({"value": ["own"]})


class _NoEntry(AkshareToMySql):
    def __init__(self) -> None:
        super().__init__(DB_CONFIG)


class _Helper(_NoEntry):
    """A helper subclass that defines no entry point of its own."""


class _RealScript(AkshareToMySql):
    def __init__(self) -> None:
        super().__init__(DB_CONFIG)

    def fetch_data(self, **kwargs: object) -> pd.DataFrame:
        return pd.DataFrame()


def _module_with(**members: object) -> types.ModuleType:
    module = types.ModuleType(__name__)
    module.__dict__.update(members)
    return module


class _ResolutionOnly:
    """The two resolution helpers, without the session `AkshareScriptService` needs."""

    _legacy_script_instance = AkshareScriptService._legacy_script_instance
    _resolve_module_callable = AkshareScriptService._resolve_module_callable


def test_run_delegates_to_the_subclasses_fetch_data_and_passes_parameters_through() -> None:
    script = _FetchOnly()

    frame = script.run(symbol="sh600000")

    assert script.seen == {"symbol": "sh600000"}
    assert frame["value"].tolist() == [1]


def test_a_subclass_that_defines_its_own_run_is_not_replaced_by_the_base() -> None:
    assert _OwnRun.run is not AkshareToMySql.run
    assert _OwnRun().run()["value"].tolist() == ["own"]


def test_the_base_declares_the_contract_for_mypy_but_grows_no_runtime_fetch_data() -> None:
    """`hasattr(instance, "fetch_data")` is how the driver picks the entry point."""
    assert "fetch_data" not in vars(AkshareToMySql)
    assert not hasattr(_NoEntry(), "fetch_data")

    with pytest.raises(AttributeError, match="fetch_data"):
        _NoEntry().run()


def test_the_driver_scan_skips_a_class_that_only_inherits_the_entry_point() -> None:
    module = _module_with(helper=_Helper, imported_base=AkshareToMySql, script=_RealScript)

    instance = _ResolutionOnly()._legacy_script_instance(module)

    assert isinstance(instance, _RealScript)


def test_a_run_only_script_still_resolves_to_its_own_run() -> None:
    module = _module_with(script=_OwnRun)

    resolved = _ResolutionOnly()._resolve_module_callable(module, "main")

    assert resolved is not None
    assert resolved.__self__.__class__ is _OwnRun
    assert resolved.__name__ == "run"
