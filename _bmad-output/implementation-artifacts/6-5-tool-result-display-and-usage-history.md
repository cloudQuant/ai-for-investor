# Story 6.5: Tool Result Display and Usage History

Status: ready-for-dev

## Story

As a user,  
I want to view my tool job status, results, and history,  
so that I can learn from previous runs.

## Acceptance Criteria

1. User can view their own job list.
2. User can view status and result for their own job.
3. Result output size is limited.
4. Sensitive information is filtered before result display where applicable.
5. Frontend handles queued, running, succeeded, failed, and timeout states.

## Tasks / Subtasks

- [x] Add safe job response serialization with result truncation and sensitive text filtering. (AC: 2, 3, 4)
- [x] Enforce own-job history and detail responses for authenticated verified users. (AC: 1, 2)
- [x] Add frontend job history page with status labels for queued, running, succeeded, failed, and timeout. (AC: 1, 5)
- [x] Add frontend job detail page showing status, timestamps, result, and safe failure message. (AC: 2, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Job result display must never expose secrets, raw stack traces, credentials, or oversized output.
- Frontend should show understandable state labels and safe empty states.
- Existing job ownership checks must remain intact.

### Project Structure Notes

- Backend API: `backend/app/api/v1/tools.py`.
- Backend schema: `backend/app/schemas/tool.py`.
- Backend tests: `backend/tests/test_tool_result_display_history.py`.
- Frontend pages: `frontend/pages/tools/jobs/index.vue`, `frontend/pages/tools/jobs/[job_id].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.5 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_result_display_history.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py tests/test_tool_manifest_admin_configuration.py tests/test_tool_job_creation_ownership.py tests/test_tool_worker_state_machine.py tests/test_tool_result_display_history.py -q ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added safe tool job response serialization with result truncation and sensitive text filtering.
- Preserved authenticated verified user ownership checks for job list/detail.
- Added frontend tool job history page with state-aware labels and previews.
- Added frontend tool job detail page with timestamps, parameters, results, and safe failure message display.

### File List

- `backend/app/api/v1/tools.py`
- `backend/tests/test_tool_result_display_history.py`
- `frontend/pages/tools/jobs/index.vue`
- `frontend/pages/tools/jobs/[job_id].vue`
- `_bmad-output/implementation-artifacts/6-5-tool-result-display-and-usage-history.md`
- `_bmad-output/implementation-artifacts/6-5-tool-result-display-and-usage-history-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
