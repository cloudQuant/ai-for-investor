# Story 1.4: Request Logging and Request ID Baseline

Status: ready-for-dev

## Story

As an operator,  
I want request IDs and structured logs,  
so that backend failures can be traced across API responses and logs.

## Acceptance Criteria

1. Each HTTP request receives an `X-Request-ID` response header.
2. Structured logging includes the request ID for request-scoped messages.
3. Unhandled exception logs include the request path and error message.
4. Error responses expose a request ID without leaking stack traces.
5. The logging configuration can be adjusted through environment settings.

## Tasks / Subtasks

- [x] Add request logging tests. (AC: 1, 2)
  - [x] Verify middleware emits `X-Request-ID`.
  - [x] Verify request start/completion log events include `request_id`, path, method, and status code.
- [x] Add failure logging tests. (AC: 2, 3, 4)
  - [x] Verify failed middleware calls log `request_failed` with path, error, and `request_id`.
  - [x] Verify global exception handler logs `unhandled_exception` with path, error, and `request_id`.
  - [x] Verify structured error response includes request ID and does not expose stack trace text.
- [x] Add logging configuration test. (AC: 5)
  - [x] Verify logging level can be applied from configured values.
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Keep the request ID short enough for local readability but present in logs and responses.
- Preserve Story 1.1 behavior for `/health`, `/openapi.json`, and router prefixes.
- Avoid leaking exception stack traces in API responses.
- Keep logging configuration environment-driven through `LOG_LEVEL`.

### Project Structure Notes

- Backend app entrypoint and middleware: `backend/app/main.py`.
- Backend request logging tests: `backend/tests/test_request_logging.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 1 and Story 1.4 acceptance criteria.
- `backend/.env.example` — `LOG_LEVEL` environment contract.
- `docs/迭代01/04-技术设计文档.md` — backend observability baseline.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added request lifecycle logging for started, completed, and failed requests.
- Added explicit request IDs to structured request and exception log fields.
- Added environment-driven logging configuration through `configure_logging()` and `LOG_LEVEL`.
- Verified backend tests through the project quality script.

### File List

- `backend/app/main.py`
- `backend/tests/test_request_logging.py`
- `_bmad-output/implementation-artifacts/1-4-request-logging-and-request-id-baseline.md`
- `_bmad-output/implementation-artifacts/1-4-request-logging-and-request-id-baseline-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
