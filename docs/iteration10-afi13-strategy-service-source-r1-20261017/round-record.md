# AFI13 strategy ServiceExecution source contract — R1

This round binds an explicitly trusted AI-research paper profile to the signed, materialized strategy module and requires the managed-order metadata consumed by the existing Backtrader ServiceExecution adapter. The ordinary profile registry still requires its normal server-side strategy mapping; the AI paper profile is selected only through the manager's ephemeral server-attested launch path.

The selected source files are:

- `src/backend/app/services/workspace_unit_runtime.py` — 82,171 bytes, SHA-256 `bec61547b4c83ada8109ce94a8eb01af6348b0b3914fee0e7e6f5f498f542e02`.
- `src/backend/app/services/live_trading/service_execution_launch.py` — 36,568 bytes, SHA-256 `54ba4ec4f0c0058aeabb5a19e101c070c93d71258efa898b8f961f27db9b4e73`.
- `src/backend/app/services/live_trading/manager.py` — 85,961 bytes, SHA-256 `4550eba26fd7cc04ddbc78d911e038d35366598b674bc00fa4fafff3f8b9787d`. Only the AI-paper launch hunks are in scope; parallel manager changes are excluded.
- `src/backend/tests/test_ai_research_paper_service_strategy_contract.py` — 8,618 bytes, SHA-256 `a2a38c2e13ae077e2681bab052b431bd866c1a8ddd23b7f0cf26bcf6dc77b6b7`.

Source-only acceptance used the project Python 3.12.10 virtual environment and ran the two selectors in that test file with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and explicit `-p pytest_asyncio.plugin`. Result: 2 passed, 0 failed/errors/skips in 6.60 seconds; two pytest configuration warnings report the unregistered `timeout` and `timeout_method` options. Captured stdout, stderr, JUnit, command metadata, and matching pre/post source pins are in `D:/source_code/ai-for-investor/.codex-tmp/afi13-strategy-service-source-r5-20261017/`.

The first configured attempt disabled pytest-asyncio and failed both autouse async-fixture setups before either test body ran. With the plugin loaded, the next run found that the new validator imported `_runtime_config_payload` from the wrong module; it is defined in `ai_research_provenance.py`. The import was corrected and the exact two selectors then passed. Independent static review by `review_bt_v3_cpf` returned GO_STATIC for the final pins and confirmed the correction does not introduce a direct import cycle.

Evidence is limited to source contracts and profile selection. This round does not prove strategy-start HTTP, the materialized run.py-to-Cerebro-to-adapter path, a ServiceHost integration, provider/account behavior, or formal AFI13 acceptance.
