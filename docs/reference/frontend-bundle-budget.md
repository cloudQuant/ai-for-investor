# Frontend Bundle Budget

This document records the active frontend bundle gates and the reproducible
Iteration 200 baseline. The build manifest is the source of truth for entry and
route asset closures; the CI check is `scripts/ci/check_bundle_size.sh`.

## Active hard budgets

| Measurement | Budget | What is counted |
|---|---:|---|
| Vite entry chunk gzip-9 size | ≤ 307,200 bytes | The `file` of the single `isEntry` manifest record. |
| Entry static closure gzip-9 size | ≤ 655,360 bytes (640 KiB) | Every JS/CSS/asset file reached through the entry's transitive static `imports`, including vendor chunks. |
| `/login` initial closure gzip-9 size | ≤ 655,360 bytes (640 KiB) | The union of the entry and `/login` static `imports` closures, including vendor chunks. |
| Largest initial JS gzip-9 size | ≤ 552,960 bytes (540 KiB) | The largest individual JS file in the union of the entry and `/login` initial closures, including vendor chunks. |
| Entry static initial JS count | ≤ 4 files | JavaScript in the entry's transitive `imports` closure, including vendor chunks. |
| `/login` static initial JS count | ≤ 4 files | JavaScript in the union of the entry and `/login` route `imports` closures, including vendor chunks. |

The entry and `/login` closures are reported with their complete asset lists
and aggregate raw/gzip-9 sizes. CSS and other manifest assets contribute to
closure-size limits, while only JavaScript contributes to initial-JS count and
largest-file limits. No vendor chunk is filtered out. The existing direct
entry 300 KiB gzip limit and four-JS caps are unchanged. Dynamic imports remain
reported separately and do not enter any first-load budget.

Whole-build JS/CSS size (≤ 20,000 KiB) and largest JS/CSS asset
(≤ 8,000 KiB) remain advisory warnings, not hard gates. CI separately runs the
existing ≤ 10% PR entry-chunk growth ratchet when a base build artifact is
available; that ratchet does not replace these manifest-based closure checks.

## Closure semantics and failure behavior

`vite.config.ts` enables `build.manifest`, producing
`src/frontend/dist/.vite/manifest.json` on a production build.
`scripts/ci/list_route_assets.mjs` uses only that manifest:

- The entry's initial closure follows only Vite `imports` edges.
- The selected route's initial closure follows only its `imports` edges and is
  combined with the entry closure for the first-load report.
- The delayed report follows `dynamicImports` edges (and each dynamic chunk's
  static `imports`) recursively. It is reported separately and never charged
  to an initial-load count or size gate. Since the app entry owns the router's
  lazy route table, this delayed report includes all dynamically reachable app
  routes, not just chunks used by the selected page.
- Manifest `file`, `css`, and `assets` references must resolve to files within
  `dist`. A missing or malformed manifest, broken graph edge, unsupported or
  unreachable route source, unsafe path, or missing output asset fails closed.
  There is no filename-scan fallback for closure computation.

The route helper supports line output with `--kind=entry-file`,
`entry-initial-js`, `initial-js`, `delayed-js`, `initial`, or `delayed`; pass
`--format=json` for the complete report. The bundle gate's advisory whole-build
totals intentionally scan emitted JS/CSS files, but that scan is not used to
resolve routes or calculate either closure.

## Iteration 200 measured baseline

Build date: 2026-09-22. Runtime: Node.js v20.20.2, npm 10.8.2, Vite 6.4.3.
Command:

```bash
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  /opt/homebrew/opt/node@20/bin/npm --prefix src/frontend run build
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  bash scripts/ci/check_bundle_size.sh src/frontend/dist
```

The build completed successfully and emitted `.vite/manifest.json`. Vite printed
advisory warnings for large minified chunks; those warnings do not weaken or
override the hard gates above.

### First-load closures

Measured by the manifest helper and the bundle gate. Gzip values are the sum of
each referenced asset compressed independently with `gzip -9` (not a CDN
transfer measurement).

| Closure | Assets | JS | Raw bytes | Gzip-9 bytes | JS files included in the hard count |
|---|---:|---:|---:|---:|---|
| Entry static | 4 | 2 | 2,192,935 | 616,170 | `application-vendor-Cq4J1uQ9.js`, `index-BiB88IjV.js` |
| `/login` initial | 7 | 4 | 2,202,406 | 619,716 | `AuthFrame.vue_vue_type_style_index_0_lang-CwHiKtGd.js`, `LoginPage-BJm40Qkm.js`, `application-vendor-Cq4J1uQ9.js`, `index-BiB88IjV.js` |
| `/login` delayed, report-only | 106 | 62 | 7,894,463 | 2,096,728 | Not counted in either initial-load budget. |

Entry static closure assets:

- `assets/application-vendor-B0H8TDX-.css`
- `assets/application-vendor-Cq4J1uQ9.js`
- `assets/index-BiB88IjV.js`
- `assets/index-lE_K1S2I.css`

`/login` initial closure adds:

- `assets/AuthFrame-DC6ODfEa.css`
- `assets/AuthFrame.vue_vue_type_style_index_0_lang-CwHiKtGd.js`
- `assets/LoginPage-BJm40Qkm.js`

The direct entry asset was `assets/index-BiB88IjV.js`: 96,314 raw bytes and
31,858 gzip-9 bytes. Other sizeable JS assets (raw bytes / gzip-9 bytes) were:

| Asset | Raw bytes | Gzip-9 bytes | Initial or delayed |
|---|---:|---:|---|
| `application-vendor-Cq4J1uQ9.js` | 1,697,398 | 527,484 | Initial; included in both closures and the 540 KiB individual-file hard budget. |
| `echarts-DU_99LXV.js` | 1,135,479 | 380,428 | Delayed where its charts are used. |
| `monaco-editor-BsWdplN2.js` | 4,487,906 | 1,146,455 | Delayed; not in `/login` or `/strategies` initial JS. |

The `monaco-editor` package and Monaco worker assets are dynamically loaded by
`MonacoEditor.vue`; the strategy code tab is lazy. The workspace optimization
tab is an async component mounted on first tab activation. The unused
`echarts-gl` side-effect import was removed after confirming there were no
`echarts-gl` API calls or other source references.

## Reproduce the route report and gates

Run from the repository root with Node 20 on `PATH`:

```bash
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  node scripts/ci/list_route_assets.mjs /login src/frontend/dist --format=json
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  node scripts/ci/list_route_assets.mjs /strategies src/frontend/dist --kind=initial-js
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  node scripts/ci/list_route_assets.mjs /strategies src/frontend/dist --kind=delayed-js
PATH="/opt/homebrew/opt/node@20/bin:$PATH" \
  bash scripts/ci/check_bundle_size.sh src/frontend/dist
```

The gate should report the direct entry gzip, entry and `/login` static closure
gzip budgets, largest individual initial JS gzip size, complete initial JS
counts and asset lists, and the separately reported delayed closure. Closure
and largest-file budgets include vendor chunks. Do not raise the hard
thresholds to make a failing build green; reduce or defer assets while keeping
vendor chunks included in every relevant measurement.
