# Collection plane: the last 7 errors on dev `96741b8a`, attributed line by line

Measured with the CI mirror (`/tmp/it204/venv-ci`: Python 3.11, `config/requirements-dev.lock`,
mypy 1.20.2) and a fresh `--cache-dir`, `--config-file config/mypy_collection.ini`,
target `app/data_fetch/scripts`. Total `errors=7 checked=1108`.

| # | file:line | code | fixed by | after #319 |
|---|---|---|---|---|
| 1 | `common/daily/macro_china_urban_unemployment.py:88` | arg-type (`json=dict[str, Sequence[Collection[str]]]`) | #319 | gone |
| 2 | `futures/hourly/futures_spot_sys.py:44` | assignment (`str \| AttributeValueList` → `str`) | #319 | gone |
| 3 | `stocks/daily/stock_hk_hot_rank_em.py:46` | arg-type (`json=dict[str, object]`) | #319 | gone |
| 4 | `stocks/daily/stock_hot_rank_em.py:46` | arg-type (same) | #319 | gone |
| 5 | `stocks/daily/stock_hot_up_em.py:46` | arg-type (same) | #319 | gone |
| 6 | `futures/monthly/dce_delivery_data.py:5` | import-untyped (`dateutil.relativedelta`) | — | **remains** |
| 7 | `futures/weekly/daily_market_data.py:7` | import-untyped (`dateutil.relativedelta`) | — | **remains** |

So the plane's sequence is: 67 (dev `3325626f96`) → 7 (#314) → **2** (#319) → 0.

The last two are not code defects: the lock simply has no `types-python-dateutil`. Measured cost
of adding it: collection **−2**, app scope **±0** (window: batch `#320`). That is a dependency
decision for the owner, not a code change to smuggle into a cleanup PR; until it is made, the
baseline freezes at **2**, not 0.

This file is the attribution the baseline PR cites. It is not a substitute for the CI reading:
the baseline itself must be frozen from the CI job's own `errors=` line.
