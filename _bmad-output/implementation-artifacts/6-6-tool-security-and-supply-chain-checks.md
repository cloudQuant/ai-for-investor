# Story 6.6: Tool Security and Supply Chain Checks

Status: ready-for-dev

## Story

As a platform owner,  
I want tool security checks,  
so that third-party tool risk is assessed before publication.

## Acceptance Criteria

1. Tool onboarding includes license review.
2. Tool onboarding includes dependency and image vulnerability review where applicable.
3. Tool containers use read-only filesystem and temporary cleanup where applicable.
4. Default outbound network access is denied unless a domain whitelist is approved.
5. High-risk trading or broker-connected functions remain excluded from MVP execution.

## Tasks / Subtasks

- [x] Add manifest security review metadata for license, vulnerability, container, network, and capabilities. (AC: 1, 2, 3, 4, 5)
- [x] Validate security review metadata during manifest create/update. (AC: 1, 2, 3, 4, 5)
- [x] Block publication of tools that fail supply-chain or MVP execution policy checks. (AC: 1, 2, 3, 4, 5)
- [x] Add backend tests for security review, network whitelist approval, container policy, and broker/live trading exclusion. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update Epic 6 status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Security checks must happen before tool publication.
- Default network policy should be denied.
- Broker-connected or live trading capabilities are excluded from MVP execution even if a tool is otherwise low risk.

### Project Structure Notes

- Backend model: `backend/app/models/tool.py`.
- Backend schema: `backend/app/schemas/tool.py`.
- Backend API: `backend/app/api/v1/tools.py`.
- Backend tests: `backend/tests/test_tool_security_supply_chain.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 6.6 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_tool_security_supply_chain.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_tool_catalog_detail.py tests/test_tool_manifest_admin_configuration.py tests/test_tool_job_creation_ownership.py tests/test_tool_worker_state_machine.py tests/test_tool_result_display_history.py tests/test_tool_security_supply_chain.py -q ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added manifest `security_review` metadata persistence and API schemas.
- Added license, dependency scan, image scan, image digest, container read-only, tmp cleanup, network whitelist approval, and capability exclusion checks.
- Enforced security review during manifest create/update.
- Revalidated manifest security before tool publication.
- Updated Story 6.2 manifest fixtures to include approved security review metadata.

### File List

- `backend/app/models/tool.py`
- `backend/app/schemas/tool.py`
- `backend/app/api/v1/tools.py`
- `backend/tests/test_tool_security_supply_chain.py`
- `backend/tests/test_tool_manifest_admin_configuration.py`
- `_bmad-output/implementation-artifacts/6-6-tool-security-and-supply-chain-checks.md`
- `_bmad-output/implementation-artifacts/6-6-tool-security-and-supply-chain-checks-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
