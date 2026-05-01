# Story 6.4: Worker Execution and Job State Machine

Status: ready-for-dev

## Story

As an operator,  
I want tool jobs to run asynchronously with clear states,  
so that web requests remain responsive and failures are traceable.

## Acceptance Criteria

1. Job states include queued, running, succeeded, failed, and timeout.
2. Worker updates job state and timestamps during execution.
3. Jobs enforce configured timeout and resource boundaries.
4. Failed jobs capture safe failure reasons.
5. Job ID links API requests, worker logs, and frontend status.

## Tasks / Subtasks

- [x] Add worker execution service with queued/running/succeeded/failed/timeout transitions. (AC: 1, 2)
- [x] Enforce manifest timeout and resource limits during worker execution. (AC: 3)
- [x] Sanitize failure reasons before storing them on jobs. (AC: 4)
- [x] Preserve job ID and request ID linkage in worker context. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Worker execution must not run arbitrary user-provided code.
- Execution is represented through a controlled executor boundary for tests and future worker integration.
- Stored failure messages must avoid leaking secrets, stack traces, or raw command details.

### Project Structure Notes

- Backend model: `backend/app/models/tool.py`.
- Worker service: `backend/app/services/tool_worker.py`.
- Backend tests: `backend/tests/test_tool_worker_state_machine.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.4 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_worker_state_machine.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py tests/test_tool_manifest_admin_configuration.py tests/test_tool_job_creation_ownership.py tests/test_tool_worker_state_machine.py -q ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added controlled worker execution service with explicit executor boundary.
- Added queued, running, succeeded, failed, and timeout state transitions.
- Added worker-side timeout, CPU, and memory policy enforcement.
- Added safe failure reason mapping to avoid leaking raw exceptions.
- Added worker execution context carrying `job_id` and `request_id`.

### File List

- `backend/app/services/tool_worker.py`
- `backend/tests/test_tool_worker_state_machine.py`
- `_bmad-output/implementation-artifacts/6-4-worker-execution-and-job-state-machine.md`
- `_bmad-output/implementation-artifacts/6-4-worker-execution-and-job-state-machine-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
