# Story 6.1: Tool Catalog and Tool Detail Pages

Status: ready-for-dev

## Story

As a visitor,  
I want to browse tool descriptions,  
so that I can understand available AI trading and investing demos before logging in.

## Acceptance Criteria

1. Tool list is publicly visible.
2. Tool detail shows source project, license, risk level, supported mode, resource cost, and usage limitations.
3. High-risk tools can be configured only as documentation or external-demo mode.
4. Tool detail includes financial and execution risk reminders.
5. Tool list distinguishes runnable demos from documentation-only tools.

## Tasks / Subtasks

- [x] Add public catalog metadata for source project, resource cost, usage limitations, and risk reminders. (AC: 2, 4)
- [x] Ensure tool list remains public and distinguishes runnable demos from documentation-only tools. (AC: 1, 5)
- [x] Enforce high-risk tool mode safety in public responses. (AC: 3)
- [x] Add public tool detail frontend page. (AC: 2, 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Public tool pages must avoid investment advice and return guarantees.
- Runnable demos must be visually distinguished from documentation-only tools.
- High-risk and extreme-risk tools must not be exposed as internally runnable demos.

### Project Structure Notes

- Backend model: `backend/app/models/tool.py`.
- Backend schema: `backend/app/schemas/tool.py`.
- Backend API: `backend/app/api/v1/tools.py`.
- Backend tests: `backend/tests/test_tool_catalog_detail.py`.
- Frontend list page: `frontend/pages/tools/index.vue`.
- Frontend detail page: `frontend/pages/tools/[slug].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.1 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added tool metadata fields for resource cost, usage limitations, financial risk reminders, and execution risk reminders.
- Added `access_type` derived signal for runnable demo, external demo, and documentation-only tools.
- Enforced public safety guard so high/extreme-risk tools cannot be exposed as internal runnable demos.
- Added public tool detail page and updated the catalog page to distinguish access type.

### File List

- `backend/app/models/tool.py`
- `backend/app/schemas/tool.py`
- `backend/app/api/v1/tools.py`
- `backend/tests/test_tool_catalog_detail.py`
- `frontend/pages/tools/index.vue`
- `frontend/pages/tools/[slug].vue`
- `_bmad-output/implementation-artifacts/6-1-tool-catalog-and-tool-detail-pages.md`
- `_bmad-output/implementation-artifacts/6-1-tool-catalog-and-tool-detail-pages-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
