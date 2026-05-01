# Story 6.3: Tool Job Creation and Ownership

Status: ready-for-dev

## Story

As a verified user,  
I want to create tool jobs,  
so that I can run approved low-risk demos.

## Acceptance Criteria

1. Only authenticated and verified users can create tool jobs.
2. Job input is validated against the tool manifest.
3. Job ownership is stored with the user.
4. Users cannot view other users' private job results.
5. Unauthenticated users are guided to login when attempting to run a tool.

## Tasks / Subtasks

- [x] Add job parameter validation against manifest allowed schema. (AC: 2)
- [x] Restrict job creation to authenticated verified users and approved low-risk internal demos. (AC: 1, 5)
- [x] Store job ownership and enforce ownership on list/detail endpoints. (AC: 3, 4)
- [x] Add backend tests for authentication, verification, manifest validation, and ownership. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Tool execution must be limited to approved internal demos with published configuration.
- Parameters must be declared in the manifest `parameters_schema.allowed` map.
- Users must only see their own jobs.

### Project Structure Notes

- Backend model: `backend/app/models/tool.py`.
- Backend schema: `backend/app/schemas/tool.py`.
- Backend API: `backend/app/api/v1/tools.py`.
- Backend tests: `backend/tests/test_tool_job_creation_ownership.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.3 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_job_creation_ownership.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py tests/test_tool_manifest_admin_configuration.py tests/test_tool_job_creation_ownership.py -q ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added manifest-backed job parameter validation.
- Restricted job creation to authenticated, verified users.
- Restricted executable jobs to published low-risk internal tools.
- Preserved user ownership on created jobs and cross-user job detail protection.
- Added login guidance for anonymous tool run attempts.

### File List

- `backend/app/api/v1/tools.py`
- `backend/tests/test_tool_job_creation_ownership.py`
- `_bmad-output/implementation-artifacts/6-3-tool-job-creation-and-ownership.md`
- `_bmad-output/implementation-artifacts/6-3-tool-job-creation-and-ownership-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
