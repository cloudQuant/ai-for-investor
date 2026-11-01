# Iteration10 AFI13 generated managed Broker construction

Repository: ai-for-investor, existing dev. Base: a4337a7da8bdb4d22c8623120051b33a140dea31.

The generated runner created the default BackBroker even for a server-selected service profile, so ServiceExecutionSession rejected the actual R8 strategy process as INVALID_BROKER. Profile runs now construct the ordinary BtApiStore/BtApiBroker with autostart disabled and zero initial cash/value, matching the existing Backtrader service-session example. An inert local client has no balance or order-write method; the later validated session owns the managed adapter. Offline runs retain BackBroker and their configured initial cash.

Root regression: `tests/test_strategy_runtime_support.py::TestWorkspaceUnitRuntime::test_generated_runner_uses_managed_store_only_for_server_profile`, 1 passed, pytest exit 0; 899 source hashes and AFI HEAD unchanged. The test executes the actual generated script for service and offline modes and captures the real broker/store before Cerebro.run. Output: `D:/temp/afi13-managed-broker-unit-r2-20261017/`. The earlier R1 fixture imported a nonexistent backbroker module; its failed output is preserved, and only that import changed to bbroker.

Evidence is broker-construction unit coverage only: run is intercepted, so full ServiceExecutionSession attachment and account state require the next HTTP integration. The example's provider=okx matches the current R8 profile; this round does not establish CTP/non-OKX profile behavior. Independent static review found the two-file fix coherent with that boundary. No full AFI13 or provider/account PASS is claimed.
