# Code Review: Story 3.4 Markdown Rendering and Content Safety

**Date:** 2026-04-30  
**Story:** `_bmad-output/implementation-artifacts/3-4-markdown-rendering-and-content-safety.md`  
**Review mode:** full  
**Decision:** Approved

## Scope Reviewed

- `backend/app/api/v1/blog.py`
- `backend/tests/test_public_blog.py`
- `frontend/pages/blog/[slug].vue`
- `_bmad-output/implementation-artifacts/3-4-markdown-rendering-and-content-safety.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Acceptance Audit

| Acceptance Criterion | Result | Evidence |
|---|---|---|
| Markdown content renders headings, lists, links, code blocks, and tables. | Pass | `render_markdown_content` uses Markdown extensions and tests assert heading, list, link, code, and table output. |
| Rendered Markdown is sanitized against XSS. | Pass | Rendering passes through `bleach.clean` with explicit allowlists. |
| External links are handled safely. | Pass | External HTTP(S) anchors receive `rel="noopener noreferrer"` and `target="_blank"`; tests cover this. |
| Code blocks are readable on supported themes. | Pass | Frontend Markdown styles provide readable block/code layout using existing theme tokens. |
| Unsafe HTML or scripts do not execute in published articles. | Pass | Tests verify scripts, event handlers, and `javascript:` URLs are removed from rendered HTML. |

## Verification Evidence

Commands run from repository root:

```bash
python3 - <<'PY'
import subprocess, sys
completed = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_public_blog.py', '-vv'], cwd='backend', text=True, capture_output=True, timeout=120, check=False)
print(completed.stdout)
print(completed.stderr)
raise SystemExit(completed.returncode)
PY
```

```bash
python3 - <<'PY'
import subprocess, sys
completed = subprocess.run(['npm', 'run', 'typecheck'], cwd='frontend', text=True, capture_output=True, timeout=120, check=False)
print(completed.stdout)
print(completed.stderr)
raise SystemExit(completed.returncode)
PY
```

```bash
python3 scripts/quality_check.py --timeout 120 --run-backend-tests
```

Observed result:

```text
tests/test_public_blog.py: 6 passed
frontend typecheck: exit code 0
PASS cmd:backend:pytest: ============================== 61 passed in 2.33s ==============================
SUMMARY total=96 passed=96 failed=0
```

## Findings

### Patched During Story

1. **Blog detail previously displayed raw Markdown as plain text**
   - Location: `frontend/pages/blog/[slug].vue`
   - Fix: switched detail display to `v-html` using server-provided `rendered_content`.

2. **API response did not include rendered safe HTML**
   - Location: `backend/app/api/v1/blog.py`
   - Fix: added `rendered_content` in `_post_to_detail_response`, covering public detail and management preview responses.

3. **Markdown rendering and XSS sanitization were missing**
   - Location: `backend/app/api/v1/blog.py`
   - Fix: added `render_markdown_content` with `markdown` rendering and `bleach` sanitization allowlists.

4. **External link hardening was missing**
   - Location: `backend/app/api/v1/blog.py`
   - Fix: external HTTP(S) links are rewritten with `rel="noopener noreferrer"` and `target="_blank"`.

5. **No regression tests existed for Markdown content safety**
   - Location: `backend/tests/test_public_blog.py`
   - Fix: added tests covering Markdown shape, rendered content response, safe external links, and unsafe HTML/script removal.

### Deferred Follow-Ups

1. **Syntax highlighting theme can be enhanced later**
   - Current implementation makes code blocks readable. Dedicated language color highlighting can be introduced when UI theme requirements are stricter.

2. **Renderer can be extracted into a content service later**
   - Current implementation is localized to the blog API. If more modules need Markdown rendering, extract the renderer into a shared content utility.

## Review Conclusion

Story 3.4 satisfies all acceptance criteria and is approved. Move Story 3.4 to `done`. Recommended next item: Story 3.5 SEO, RSS, and Structured Metadata.
