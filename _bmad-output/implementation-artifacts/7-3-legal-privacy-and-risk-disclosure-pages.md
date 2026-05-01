# Story 7.3: Legal, Privacy, and Risk Disclosure Pages

Status: ready-for-dev

## Story

As a platform owner,  
I want legal and risk disclosure pages,  
so that MVP boundaries are visible to users.

## Acceptance Criteria

1. User agreement page exists.
2. Privacy policy page exists.
3. Financial risk disclaimer page exists.
4. Disclaimer states the platform is for education and research and does not provide investment advice.
5. Public content and tool pages link to relevant disclaimer information.

## Tasks / Subtasks

- [x] Add user agreement page. (AC: 1)
- [x] Add privacy policy page. (AC: 2)
- [x] Add financial risk disclaimer page. (AC: 3, 4)
- [x] Link legal and disclaimer pages from global footer and relevant public/tool pages. (AC: 5)
- [x] Add automated structure guard for legal/privacy/risk disclosure pages and links. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Wording must preserve MVP compliance boundaries: education/research only, no investment advice, no return promises, no broker/exchange binding, no user funds, and no real trading API execution.
- Pages should be static frontend pages and use existing theme tokens.

### Project Structure Notes

- Legal pages: `frontend/pages/legal/**`.
- Global footer: `frontend/layouts/default.vue`.
- Coverage guard: `backend/tests/test_legal_privacy_risk_disclosure_pages.py`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 7.3 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_legal_privacy_risk_disclosure_pages.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added user agreement, privacy policy, and financial risk disclaimer pages under `frontend/pages/legal`.
- Legal/risk wording preserves MVP boundaries: education/research only, no investment advice, no returns promise, no broker/exchange account binding, no user funds, no real trading API execution, and no arbitrary user code execution.
- Added footer links to all legal pages.
- Added risk disclaimer links from homepage, blog detail, tools list, tool detail, and open-source project detail.
- Added automated structure guard for legal page existence, required compliance wording, and disclaimer links.

### File List

- `frontend/pages/legal/terms.vue`
- `frontend/pages/legal/privacy.vue`
- `frontend/pages/legal/risk-disclaimer.vue`
- `frontend/layouts/default.vue`
- `frontend/pages/index.vue`
- `frontend/pages/blog/[slug].vue`
- `frontend/pages/tools/index.vue`
- `frontend/pages/tools/[slug].vue`
- `frontend/pages/open-source/[id].vue`
- `backend/tests/test_legal_privacy_risk_disclosure_pages.py`
- `_bmad-output/implementation-artifacts/7-3-legal-privacy-and-risk-disclosure-pages.md`
- `_bmad-output/implementation-artifacts/7-3-legal-privacy-and-risk-disclosure-pages-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
