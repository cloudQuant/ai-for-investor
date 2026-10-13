# Iteration 202 production init/signal-forwarding image receipt

- Purpose: verify the production image configuration replaces the shell with Gunicorn so Docker init can forward termination signals. This is image-build/config evidence only; no service/container was started.
- Build command (secrets omitted; no secrets were supplied):
  ```sh
  docker buildx build --platform linux/arm64 --load --progress=plain \
    --build-context backtrader_repo=/tmp/ai-investor-backtrader-iter202-build.git \
    -f /tmp/iter202-d14-prod-context/Dockerfile \
    -t iter202-d14-backend:20261012-init-final \
    /tmp/iter202-d14-prod-context
  ```
- Captured build start: `2026-10-12T11:33:02Z`.
- Captured build finish, including image load: `2026-10-12T11:33:31Z`.
- Build command exit code: `0`; complete log: `/tmp/ai-investor-iter200-202-20261012.afLb99/iter202-prod-init-build.log`.
- BuildKit showed every dependency/source/system/ownership layer as `CACHED`, including the exact locked pip install. No dependency layer was rebuilt or downloaded.
- Canonical source: `src/backend/Dockerfile`, SHA-256 `b3679ae71fc4f290836dd75a2be1b29337fb3ff11d354b4aa7ae9c6635c7b43e`.
- Effective temporary mirror Dockerfile: `/tmp/iter202-d14-prod-context/Dockerfile`, SHA-256 `58cb8e70cce3f8f420fd03b8c13073ea88ebb64525373f31a9ea7dd2a4ff9f29`.
- Canonical-vs-mirror diff is limited to (1) the BuildKit syntax directive and (2) a process-scoped Git URL rewrite for the one pip install RUN, allowing the exact pinned Backtrader dependency to use the approved local bare mirror. The mirror does not change dependency versions, lock URLs, or commits. Bare mirror: `/tmp/ai-investor-backtrader-iter202-build.git`, commit `04adc08c2deb02cbf240efbd495e5eee68b375d8`.
- Production lock: `config/requirements-prod.lock`, SHA-256 `b3e165273f2f7eef37d2cfef25d6466b379abd7d681375b020e57966d2efbb6b`; the build-context copy has the same hash.
- BuildKit export identifiers: platform manifest `sha256:d75cbb7f1d69bbf4cf58ca267ed00c984daf2fcacf12abf7abe1f07824060bfe`; image config `sha256:87cf916261f15ab578f5c0087ce6814c61c3a91febff20a777775a509c4738e6`; manifest list `sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9`.
- Docker image: `iter202-d14-backend:20261012-init-final`; `docker image inspect` reports ID `sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9`, OS `linux`, architecture `arm64`, user `appuser`, entrypoint `null`, and command `sh -c "exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile -"`.
- `.Created` from image inspection remains `2026-10-12T09:50:28.394071258Z`; it is an image configuration timestamp, not the build completion time. The build timestamps above come from the wrapper around the buildx process.
- Validation: `git diff --check -- src/backend/Dockerfile` passed; image config readback confirms `exec` is the first shell command. Runtime signal delivery, worker health, and shutdown behavior remain for the parent’s isolated D12 test.
- Build context detail: it reuses `/tmp/iter202-d14-prod-context`; its copied `src/backend/Dockerfile` file is the prior source snapshot (`ff234814a1391386f8c0a4f55a93ac854bac7158d5d5f267b5d174e26b222aec`) and is not the Dockerfile used to define this build. The effective Dockerfile passed with `-f` is `/tmp/iter202-d14-prod-context/Dockerfile`; the source-copy layer was cached. Application Python source and lock were unchanged for this CMD-only image rebuild.
