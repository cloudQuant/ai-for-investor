# Story 4.5: Forum Theme System and User Preference

Status: ready-for-dev

## Story

As a user,  
I want forum themes to be switchable and persistent,  
so that I can choose a comfortable reading experience.

## Acceptance Criteria

1. At least `fintech-trust-light` and `terminal-agent-dark` themes are available.
2. Theme switch is available to visitors and authenticated users.
3. Visitor theme preference persists locally.
4. Authenticated user theme preference persists to user preferences.
5. Theme switching does not change permissions, information architecture, or core workflows.

## Tasks / Subtasks

- [x] Validate supported theme identifiers in backend preferences. (AC: 1, 4)
- [x] Ensure visitor theme preference persists locally. (AC: 2, 3)
- [x] Persist authenticated theme changes to user preferences. (AC: 2, 4)
- [x] Keep theme switching isolated to visual presentation only. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Existing themes already include `fintech-trust-light` and `terminal-agent-dark`.
- Existing `ThemeSwitcher` is mounted in the default layout, so it is available to visitors and authenticated users.
- Visitor persistence currently uses `ui_theme` cookie.
- Authenticated persistence should use `/api/v1/preferences/me/preferences` via the frontend API wrapper.

### Project Structure Notes

- Backend API: `backend/app/api/v1/preferences.py`.
- Backend schemas: `backend/app/schemas/preference.py`.
- Frontend theme store: `frontend/stores/theme.ts`.
- Frontend theme composable: `frontend/composables/useTheme.ts`.
- Frontend theme switcher: `frontend/components/common/ThemeSwitcher.vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.5 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_theme_preferences.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Confirmed required themes are available in the existing theme catalog.
- Added backend supported-theme validation for user preference updates.
- Changed preferences update response to return the persisted preference payload.
- Kept visitor persistence via local `ui_theme` cookie.
- Added authenticated preference initialization and remote persistence on theme switch.

### File List

- `backend/app/api/v1/preferences.py`
- `backend/tests/test_forum_theme_preferences.py`
- `frontend/composables/useTheme.ts`
- `frontend/components/common/ThemeSwitcher.vue`
- `frontend/layouts/default.vue`
- `_bmad-output/implementation-artifacts/4-5-forum-theme-system-and-user-preference.md`
- `_bmad-output/implementation-artifacts/4-5-forum-theme-system-and-user-preference-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
