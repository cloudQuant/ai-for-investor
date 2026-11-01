# MIG01 live legacy Gateway fallback retirement R1

Repository: `D:\source_code\ai-for-investor`, branch `dev`. The source base at review was `c53beefb38ac37555ea39aa979d0f7ff7d49222d`.

This round makes the existing live-strategy builder fail closed when it has no trusted ServiceExecution profile and the persisted instance selects a legacy Gateway. The finite `LEGACY_GATEWAY_MIGRATION_REQUIRED` error occurs before the legacy subprocess environment builder, runtime acquisition, or retired Base Gateway import. The private `_build_gateway_launch` and `_import_gateway_runtime_classes` entrypoints independently reject before reading strategy configuration or importing the old runtime. A valid ServiceExecution profile still takes the existing path; a no-Gateway simulation retains the direct environment path.

The selected code scope is three paths: `src/backend/app/services/live_trading/manager.py` (only `_build_subprocess_env`, `_build_gateway_launch`, `_import_gateway_runtime_classes`, and their now-unused import references), `src/backend/tests/test_service_strategy_gateway_fallback.py`, and `src/backend/tests/test_live_trading_manager.py`. The manager checkout also contains disjoint AI-paper profile changes owned by another round; they are excluded from this commit. The tests replace old positive CTP/IB legacy-runtime expectations with finite zero-acquire rejection checks, and preserve a no-Gateway simulation positive case.

Reviewed checkout pins:

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `src/backend/app/services/live_trading/manager.py` | 85,962 | `022F96DF9B298B70F43BC38020DE6187336DEC8EBBEA9CD5EE0A3003CBD6912B` |
| `src/backend/tests/test_service_strategy_gateway_fallback.py` | 4,752 | `69B89A4DDF25D8F67FDAED11F5183FC791F263BA5F39888D599ED05375CEE391` |
| `src/backend/tests/test_live_trading_manager.py` | 108,575 | `A750AC07486EFE5B2A7C2F415E4669B841AB9CFEBA5C731CF76B6C6AC6AE0327` |

Independent static review by `review_bt_v3_cpf`: `GO_STATIC` at these pins, with only the manager migration hunks reviewed. The reviewer confirmed that the service-profile branch returns before the legacy rejection, the legacy environment/acquire/import path is not reached, both private legacy builders reject, and the simulation path remains available.

Author verification used the AFI backend virtual environment, Python 3.12.10, with `-X utf8` and `PYTHONUTF8=1`. The exact seven-node focus passed in one final run (7 passed in 32.23 seconds): all three `test_service_strategy_gateway_fallback.py` tests and four selected `TestGatewayLifecycle` cases for simulation, CTP, IB_WEB, and the retired launch builder. The test collection check imported the full manager test module and collected 91 tests. Ruff, `py_compile`, and `git diff --check` passed on the three source/test files. An earlier focused attempt exposed that the simulation fixture omitted its mode and therefore used the live default; the fixture now explicitly declares simulation, and the final focused run passed.

Evidence is local unit and static-source evidence only. No Host, credentials, real account, or venue was used. Formal MIG01 remains incomplete: remaining AFI Gateway manual/runtime consumers and the Base Gateway package closure are outside this round.
