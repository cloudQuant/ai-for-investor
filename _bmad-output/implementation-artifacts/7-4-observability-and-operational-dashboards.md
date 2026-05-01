# Story 7.4: Observability and Operational Dashboards

Status: ready-for-dev

## Story

As an operator,  
I want monitoring for API, worker, database, and content operations,  
so that production issues can be detected.

## Acceptance Criteria

1. API latency, error rate, and request volume are observable.
2. Worker queue backlog and job failure rate are observable.
3. Email delivery success or failure is observable.
4. Database slow query or health indicators are observable.
5. Alerts exist for critical API, worker, and storage failures.

## Tasks / Subtasks

- [x] Add API request volume, latency, and error-rate observability. (AC: 1)
- [x] Add worker backlog and job failure-rate observability. (AC: 2)
- [x] Add email delivery success/failure observability. (AC: 3)
- [x] Add database/storage health indicators. (AC: 4)
- [x] Add critical alert states for API, worker, email, database, and storage failures. (AC: 5)
- [x] Add admin operational dashboard endpoint. (AC: 1, 2, 3, 4, 5)
- [x] Add automated tests. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Use lightweight in-process metrics for MVP launch readiness; avoid adding external monitoring dependencies in this story.
- Dashboard access must remain admin-only.
- Request IDs and existing structured logs remain the trace correlation mechanism.

### Project Structure Notes

- Observability helpers: `backend/app/core/observability.py`.
- Admin endpoint: `backend/app/api/v1/admin.py`.
- Request middleware: `backend/app/main.py`.
- Worker metrics integration: `backend/app/services/tool_worker.py`.
- Test coverage: `backend/tests/test_observability_operational_dashboards.py`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 7.4 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_observability_operational_dashboards.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added lightweight in-process observability counters for API request volume, latency, error rate, worker job outcomes, and email delivery outcomes.
- Integrated API metrics into request middleware while preserving `X-Request-ID` and structured logs.
- Integrated worker job metrics into tool worker success/failure transitions.
- Integrated email delivery metrics into registration and password reset token flows.
- Added admin-only `/api/v1/admin/observability` dashboard data with API, worker, email, database, storage, and alert sections.
- Added alert rules for critical API error rate/latency, worker backlog/failure rate, email failure rate, database health, and storage health.
- Added automated coverage for observability snapshots, alert rules, and admin dashboard response shape.

### File List

- `backend/app/core/observability.py`
- `backend/app/main.py`
- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/admin.py`
- `backend/app/services/tool_worker.py`
- `backend/tests/test_observability_operational_dashboards.py`
- `_bmad-output/implementation-artifacts/7-4-observability-and-operational-dashboards.md`
- `_bmad-output/implementation-artifacts/7-4-observability-and-operational-dashboards-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
