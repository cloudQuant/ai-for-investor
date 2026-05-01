# Story 1.2: Database and Cache Connectivity Baseline

Status: ready-for-dev

## Story

As a developer,  
I want MySQL, MongoDB, and Redis connectivity configured,  
so that later modules can rely on shared persistence and queue infrastructure.

## Acceptance Criteria

1. Backend settings load MySQL, MongoDB, and Redis connection values from environment variables.
2. Local Docker Compose exposes MySQL, MongoDB, and Redis with health checks.
3. Backend startup connects to MongoDB and Redis and closes those clients on shutdown.
4. SQLAlchemy async engine is configured for MySQL.
5. Missing required secrets fail fast in development instead of silently using unsafe defaults.
6. Connectivity baseline tests verify configuration and lifecycle behavior without requiring live MySQL, MongoDB, or Redis services.

## Tasks / Subtasks

- [x] Add backend tests for database/cache configuration. (AC: 1, 4, 5, 6)
  - [x] Verify required Settings fields fail fast when missing.
  - [x] Verify SQLAlchemy engine uses the async MySQL driver and configured database.
- [x] Add backend tests for MongoDB and Redis lifecycle functions. (AC: 3, 6)
  - [x] Verify MongoDB client and database are initialized from settings.
  - [x] Verify Redis client is initialized with host, port, password, database, and decode settings.
  - [x] Verify close functions release module-level clients.
- [x] Verify Docker Compose database/cache services through existing project quality checks. (AC: 2)
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 6)
- [x] Generate code review report and update sprint status. (AC: 6)

## Dev Notes

- Tests must not require live MySQL, MongoDB, or Redis services.
- Use monkeypatching for MongoDB and Redis client constructors.
- Keep MySQL validation at configuration/engine level; do not open a database connection in this story.
- Keep production startup behavior unchanged: the default module-level FastAPI app should still connect to MongoDB and Redis during lifespan startup.

### Project Structure Notes

- Backend config: `backend/app/core/config.py`.
- MySQL module: `backend/app/db/mysql.py`.
- MongoDB module: `backend/app/db/mongodb.py`.
- Redis module: `backend/app/db/redis.py`.
- Backend tests: `backend/tests/test_connectivity_baseline.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 1 and Story 1.2 acceptance criteria.
- `docs/迭代01/04-技术设计文档.md` — MySQL, MongoDB, Redis, and worker architecture.
- `docker-compose.yml` — local MySQL, MongoDB, Redis services and health checks.
- `backend/.env.example` — backend environment configuration contract.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added connectivity baseline tests for Settings, MySQL engine configuration, MongoDB lifecycle, and Redis lifecycle.
- Updated MongoDB and Redis close functions to clear module-level client references.
- Verified backend tests through the project quality script.

### File List

- `backend/app/db/mongodb.py`
- `backend/app/db/redis.py`
- `backend/tests/test_connectivity_baseline.py`
- `_bmad-output/implementation-artifacts/1-2-database-and-cache-connectivity-baseline.md`
- `_bmad-output/implementation-artifacts/1-2-database-and-cache-connectivity-baseline-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
