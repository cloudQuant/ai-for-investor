# Story 3.6: Seed Content and Editorial Templates

Status: ready-for-dev

## Story

As a content operator,  
I want article templates and seed topics,  
so that the community can launch with credible content.

## Acceptance Criteria

1. Project review template includes use case, repository signal, setup notes, risk reminder, and license notes.
2. Weekly report template includes project highlights, updates, recommended readings, discussion prompts, and disclaimer.
3. Initial seed content list covers TradingAgents, Qlib, OpenBB, QuantStats, vectorbt, and risk methodology.
4. Content guidelines distinguish research demos from investable claims.
5. No article promises returns or gives personalized investment advice.

## Tasks / Subtasks

- [x] Create project review article template. (AC: 1)
- [x] Create weekly report article template. (AC: 2)
- [x] Create initial seed content list covering required topics. (AC: 3)
- [x] Create editorial and compliance guidelines. (AC: 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- This story is a content operations artifact, not an application code change.
- Templates must make the education/research boundary explicit.
- Seed topics should launch the blog with credible AI investing and quantitative research coverage.
- Avoid personalized advice, return promises, trading signals, broker instructions, or fund-handling claims.

### Project Structure Notes

- Editorial package: `_bmad-output/implementation-artifacts/3-6-seed-content-and-editorial-templates-package.md`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 3.6 acceptance criteria.
- `docs/迭代01/产品调研与迭代计划.md` — market/project references and risk boundaries.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added a project review template covering use case, repository signals, setup notes, risk reminder, and license notes.
- Added a weekly report template covering highlights, updates, recommended readings, discussion prompts, and disclaimer.
- Added seed content topics covering TradingAgents, Qlib, OpenBB, QuantStats, vectorbt, and risk methodology.
- Added editorial guidelines separating research demos from investable claims and prohibiting personalized investment advice.

### File List

- `_bmad-output/implementation-artifacts/3-6-seed-content-and-editorial-templates.md`
- `_bmad-output/implementation-artifacts/3-6-seed-content-and-editorial-templates-package.md`
- `_bmad-output/implementation-artifacts/3-6-seed-content-and-editorial-templates-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
