# Story 1.1: Backend Application Skeleton and Health Check

Status: ready-for-dev

## Story

As a developer,  
I want a FastAPI backend skeleton with a health endpoint and OpenAPI documentation,  
so that the team can verify the service baseline quickly.

## Acceptance Criteria

1. FastAPI application starts with the configured app name and version.
2. `GET /health` returns service status, app name, and version.
3. OpenAPI documentation is available in the local backend environment.
4. API routers follow the `/api/v1/*` prefix convention.
5. Unhandled exceptions return a structured error with `request_id`.
6. Backend smoke tests verify app metadata, health response, request ID header, OpenAPI availability, and router prefixes without requiring live MySQL, MongoDB, or Redis services.

## Tasks / Subtasks

- [x] Add backend smoke tests for the FastAPI skeleton. (AC: 1, 2, 3, 4, 5, 6)
  - [x] Verify app title and version match configuration.
  - [x] Verify `GET /health` returns `healthy`, app name, and version.
  - [x] Verify `X-Request-ID` header is emitted on HTTP responses.
  - [x] Verify `/openapi.json` is available.
  - [x] Verify API routes use the `/api/v1/*` prefix convention.
  - [x] Verify global exception handler response shape includes `error` and `request_id`.
- [x] Refactor app construction so tests can instantiate the app without connecting to external services. (AC: 6)
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 6)
- [x] Generate code review report and update sprint status. (AC: 6)

## Dev Notes

- Keep the public `app` object in `backend/app/main.py` for `uvicorn app.main:app` compatibility.
- Avoid requiring live MySQL, MongoDB, or Redis during smoke tests.
- Preserve `/health` response contract: `status`, `app`, and `version`.
- Preserve compliance boundaries from planning docs; this story must not add trading, broker, exchange, fund, advice, return-promise, or arbitrary-code-execution behavior.

### Project Structure Notes

- Backend app entrypoint: `backend/app/main.py`.
- Backend tests: `backend/tests/test_app_smoke.py`.
- Project quality entrypoint: `scripts/quality_check.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 1 and Story 1.1 acceptance criteria.
- `docs/迭代01/04-技术设计文档.md` — FastAPI, REST API, OpenAPI, modular monolith design.
- `docs/迭代01/00-文档体系与迭代开发流程.md` — Definition of Done and quality gates.
- `README.md` — backend local setup and health check command.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added a testable `create_app()` factory while preserving the module-level `app` object.
- Added backend smoke tests for metadata, health, request ID, OpenAPI, route prefix, and error response shape.
- Verified backend tests through the project quality script.

### File List

- `backend/app/main.py`
- `backend/tests/test_app_smoke.py`
- `_bmad-output/implementation-artifacts/1-1-backend-application-skeleton-and-health-check.md`
- `_bmad-output/implementation-artifacts/1-1-backend-application-skeleton-and-health-check-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
