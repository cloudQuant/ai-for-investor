# Iteration 202 D12 cold-start diagnosis (read-only)

Evidence sources:

- Parent-captured sanitized container log: `d12-clean-v2-backend-redacted.log`.
- Parent-captured `docker compose up --wait` result and timing: `d12-clean-v2-parent-receipt.json` and `d12-clean-up-v2-parent.txt`.
- Container state snapshot: `d12-clean-v2-backend-state.json`.
- Current dev image: `iter202-d12-backend-logdir:20261012-final`, manifest/image ID `sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc`.
- Offline inspection of the image reported Uvicorn `0.47.0`. Its installed `/usr/local/lib/python3.11/site-packages/uvicorn/main.py` calls `config.load_app()` before creating the `Server` and before entering `ChangeReload(...).run()` (source lines 609 onward). The reload worker then starts separately.

Observed sequence (UTC):

- Backend container start: `10:59:25.748Z`; entrypoint starts `10:59:27.419Z`.
- The configured async database probe succeeds at `10:59:38.347Z`, without any retry, and the entrypoint execs the application at `10:59:38.997Z`.
- First module-level middleware/telemetry logs appear at `11:03:05.855Z`, about 207 seconds after the entrypoint's application handoff. The second matching registration sequence appears at `11:04:37.558Z`.
- Uvicorn reports the reloader process at `11:03:21.673Z`, the server process at `11:04:45.752Z`, and begins lifespan at `11:04:45.753Z`. The migration revision read completes at `11:04:52.329Z`; the application announces ready at `11:04:55.277Z`.
- The clean `up --wait` command returned `container ... is unhealthy` at `11:03:25.377Z`, before the server process entered lifespan. Later health requests return HTTP 200 from `11:04:59Z` onward; this later state does not turn the earlier command into a pass.

Interpretation and limits:

- The entrypoint's database wait is not the observed bottleneck: it consumed about 11 seconds and succeeded on its first attempt. The lifespan database revision verification and remaining startup hooks finish in about 10 seconds.
- The long portion occurs before lifespan. `app.main` imports `app.api.router` before its local logging setup; the router imports many core and optional API modules at module load. This, plus the measured two registration sequences, is consistent with a costly initial Uvicorn app preload followed by a reload-worker import. It is a code-path explanation, not a per-module timing profile.
- There are no `WatchFiles detected changes` or `Reloading` messages in the captured sanitized log, so this run does not establish source/log watcher churn as the cause. The image and Compose both set `LOG_DIR=/var/log/ai-for-investor`, outside the watched backend tree.
- The image's effective command is `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`; Compose does not override it. `python -m app.main` is not the command, so the `if __name__ == "__main__"` block is not what causes this run's repeated import. Replacing the CLI executable with `python -m uvicorn` would use the same Uvicorn config/reload path and is not supported by this evidence as a fix. Current host/port CLI values are literal and do not interpolate Compose's `HOST`/`PORT` environment values.
- No server command, reload settings, health-check budget, application timeout, database, or service state was changed during this diagnosis.
