# Story 6.2: Tool Manifest and Admin Configuration

Status: ready-for-dev

## Story

As an administrator,  
I want tool manifests to define allowed parameters and execution boundaries,  
so that tool usage remains controlled.

## Acceptance Criteria

1. Tool manifest defines entry command or mode, allowed parameters, resource limits, timeout, and network policy.
2. Manifest validation rejects unsupported parameters and unsafe execution modes.
3. Admin can create, update, publish, unpublish, and retire tool configurations.
4. Admin changes create audit records.
5. Tools cannot execute arbitrary user-provided code.

## Tasks / Subtasks

- [x] Add manifest create/update schemas with execution boundaries. (AC: 1, 2, 5)
- [x] Add manifest validation for safe modes, parameters, timeout, resource limits, and network policy. (AC: 1, 2, 5)
- [x] Add admin endpoints for manifest create/update and tool config lifecycle. (AC: 3)
- [x] Add audit records for admin changes. (AC: 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Manifest execution must be declarative and bounded.
- Arbitrary user-provided code or shell execution must be rejected.
- Admin lifecycle status should distinguish draft, published, unpublished, and retired tools.

### Project Structure Notes

- Backend model: `backend/app/models/tool.py`.
- Backend schema: `backend/app/schemas/tool.py`.
- Backend API: `backend/app/api/v1/tools.py`.
- Backend tests: `backend/tests/test_tool_manifest_admin_configuration.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.2 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_manifest_admin_configuration.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py tests/test_tool_manifest_admin_configuration.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added manifest create/update schemas and admin-only endpoints.
- Added manifest boundary validation for safe modes, command tokens, allowed parameters, resource limits, timeout, and network policy.
- Added tool config create/update and publish, unpublish, retire lifecycle endpoints.
- Added audit records for manifest and config admin changes.
- Preserved public tool catalog compatibility with default `config_status` normalization.

### File List

- `backend/app/models/tool.py`
- `backend/app/schemas/tool.py`
- `backend/app/api/v1/tools.py`
- `backend/tests/test_tool_manifest_admin_configuration.py`
- `_bmad-output/implementation-artifacts/6-2-tool-manifest-and-admin-configuration.md`
- `_bmad-output/implementation-artifacts/6-2-tool-manifest-and-admin-configuration-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
