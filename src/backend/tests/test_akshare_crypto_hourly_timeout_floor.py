"""The crypto hourly leg's timeout floor, and the measurement that justifies it.

Without a floor in `_SCRIPT_MIN_TIMEOUT_SECONDS`, an hourly task whose ledger row
still says 600 s is cut off while it is still writing. Measured on this host on
2026-11-05: the 14:03 UTC occurrence was marked `failed` at 601 s and yet kept
committing rows until 14:18:44 (~946 s, 59,983 rows).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.akshare.script import AkshareScriptService


def _script(script_id: str, timeout: int = 600) -> SimpleNamespace:
    return SimpleNamespace(script_id=script_id, timeout=timeout)


def test_crypto_hourly_floor_outruns_the_registered_timeout() -> None:
    assert (
        AkshareScriptService._script_timeout_seconds(
            _script("crypto_hourly_market"), timeout_seconds=600
        )
        == 1800.0
    )


def test_floor_never_shrinks_a_larger_explicit_budget() -> None:
    assert (
        AkshareScriptService._script_timeout_seconds(
            _script("crypto_hourly_market"), timeout_seconds=2400
        )
        == 2400.0
    )


def test_other_scripts_keep_their_own_budget() -> None:
    # Counterfactual: a blanket raise would quietly reprice every task.
    assert (
        AkshareScriptService._script_timeout_seconds(
            _script("stock_esg_msci_sina"), timeout_seconds=600
        )
        == 600.0
    )
