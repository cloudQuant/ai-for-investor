# Iteration 10 AFI08 strategy process stop — R1

- Repository: `ai-for-investor`, branch `dev`; source base `bbae1119e6641a6ebc0a4e55e79363320dbc3c4d`.
- Scope: `LiveTradingManager.stop_instance` exact profile/run/process guard; trusted `STOP_NEW` then graceful service-strategy process stop; focused unit and local Host integration coverage.
- Acceptance: AFI backend `.venv` Python 3.12.10 focused suite, 6 passed; Ruff passed; independent static review GO.
- Evidence level: local synthetic ServiceHost/Curve and strategy subprocess only. No venue/account acceptance. Receipts keep open orders `left_open_unverified` and positions `unobserved`; unresolved STOP_NEW does not release the process or subscriptions.
