#!/bin/sh
set -eu
image=iter202-d14-backend:20261012-final
receipt=/tmp/ai-investor-iter200-202-20261012.afLb99/iter202-prod-runtime-final-receipt.log
{
  printf '%s\n' '=== lock sha256 ==='
  shasum -a 256 config/requirements-prod.lock
  printf '%s\n' '=== image id and platform ==='
  docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}} {{json .RepoDigests}}' "$image"
  printf '%s\n' '=== container identity and Python ==='
  docker run --rm --network none --entrypoint sh "$image" -c 'id; python -VV'
  printf '%s\n' '=== dependency versions and Backtrader source ==='
  docker run --rm --network none --entrypoint python "$image" -c 'import importlib.metadata as m,json; names=("alembic","Mako","asyncpg","SQLAlchemy","PyMySQL","PyJWT","urllib3","backtrader","WeasyPrint","httpx","httpcore","purgedcv","scikit-learn","joblib","threadpoolctl"); print("\\n".join(f"{name}=={m.version(name)}" for name in names)); print("backtrader.direct_url="+m.distribution("backtrader").read_text("direct_url.json"))'
  printf '%s\n' '=== pip consistency ==='
  docker run --rm --network none --entrypoint python "$image" -m pip check
  printf '%s\n' '=== Alembic heads ==='
  docker run --rm --network none --entrypoint python "$image" -m alembic heads
  printf '%s\n' '=== application import ==='
  docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e LOG_DIR=/tmp/iter202-prod-runtime-check-logs --entrypoint python "$image" -c 'from app.main import app; print(f"app_import=ok title={app.title}")'
} 2>&1 | tee "$receipt"
