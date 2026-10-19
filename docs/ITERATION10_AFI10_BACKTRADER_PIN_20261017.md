# Iteration 10 AFI10 Backtrader source pin

- AFI repository: `dev`, parent `eda84eb7ab3a0de7c8baf285ed5d16301c84417e`.
- Backtrader source: accepted local `dev` commit `4f3e6a1ca3c41c1e5a726d11cce162faec25b140`, which contains `backtrader/stores/service_execution_session.py` required by the managed strategy path.
- Scope: synchronized that exact VCS revision in `src/backend/pyproject.toml`, `src/backend/requirements.txt`, `config/requirements-prod.lock`, and `config/requirements-dev.lock`; no other lock versions were regenerated.
- Check: `src/backend/.venv/Scripts/python.exe -X utf8 scripts/ci/check_deps_sync.py` passed. No wheel build, installation, `pip check`, or Host ran in this round; those checks wait for the accepted Base gateway-tree closure.
- Release status: local release candidate only. The Backtrader revision has not been published, and no remote VCS installation is claimed.
