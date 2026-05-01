# Story 1.3: Development Environment and Quality Commands

Status: ready-for-dev

## Story

As a contributor,  
I want documented local setup, test, lint, and build commands,  
so that onboarding and PR checks are repeatable.

## Acceptance Criteria

1. README documents backend setup, frontend setup, Docker Compose startup, and health checks.
2. README documents backend test command and frontend lint/typecheck/build commands.
3. README documents required environment files and points to `backend/.env.example`.
4. README documents current database initialization approach and the migration gap.
5. README documents core project compliance boundaries.
6. A project-level quality check command verifies key setup documents, dependency manifests, BMad artifacts, and sprint status values.
7. The quality check command supports optional backend test and frontend lint/typecheck/build execution with a timeout.

## Tasks / Subtasks

- [x] Add project-level quality script. (AC: 6, 7)
  - [x] Verify required files exist.
  - [x] Verify README contains setup, environment, migration, quality, BMad, and compliance sections.
  - [x] Verify backend requirements contain core runtime and test dependencies.
  - [x] Verify frontend package scripts and dependencies.
  - [x] Verify Docker Compose includes MySQL, MongoDB, Redis, backend, and frontend services.
  - [x] Verify BMad sprint status values use legal statuses.
- [x] Update README with the unified quality check command. (AC: 1, 2, 3, 4, 5, 6, 7)
- [x] Record implementation readiness assessment. (AC: 6)
- [x] Update sprint status for Story 1.3 after implementation and review. (AC: 6)

## Dev Notes

- Use Python for the project-level quality command to avoid long shell pipelines and to support explicit timeouts.
- Keep the first implementation story scoped to project repeatability and documentation; do not start feature work here.
- Do not treat `init_db.py` as a production migration substitute. The current migration gap remains a follow-up.
- Do not imply the platform provides investment advice, broker/exchange integration, real trading, user fund handling, return promises, or arbitrary user code execution.

### Project Structure Notes

- Quality script path: `scripts/quality_check.py`.
- README path: `README.md`.
- BMad planning output path: `_bmad-output/planning-artifacts/implementation-readiness-report.md`.
- Sprint status path: `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- Current frontend package manager evidence: `frontend/pnpm-lock.yaml` exists, while `frontend/Dockerfile` uses `npm install`; this should be reviewed in a future environment consistency task.
- Current frontend lint caveat: `frontend/package.json` defines `npm run lint`, but no ESLint config was detected during story creation; this should be reviewed before enforcing lint in CI.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 1 and Story 1.3 acceptance criteria.
- `docs/迭代01/00-文档体系与迭代开发流程.md` — Definition of Ready, Definition of Done, quality gates.
- `docs/迭代01/04-技术设计文档.md` — MVP architecture and technical stack.
- `docs/迭代01/05-验收测试与上线验收文档.md` — acceptance, security, SEO, and launch gates.
- `docs/迭代01/06-需求追踪矩阵RTM.md` — requirement status maintenance rules.
- `backend/requirements.txt` — backend runtime and testing dependencies.
- `frontend/package.json` — frontend scripts and dependencies.
- `docker-compose.yml` — local development services.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120`

### Completion Notes List

- Added `scripts/quality_check.py` as the project-level quality check entrypoint.
- Added implementation readiness report.
- Updated README to document the quality check entrypoint and timeout-based optional checks.
- Updated sprint status so Epic 1 is in progress and Story 1.3 is done after review.

### File List

- `README.md`
- `scripts/quality_check.py`
- `_bmad-output/planning-artifacts/implementation-readiness-report.md`
- `_bmad-output/implementation-artifacts/1-3-development-environment-and-quality-commands.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/1-3-development-environment-and-quality-commands-review.md`
