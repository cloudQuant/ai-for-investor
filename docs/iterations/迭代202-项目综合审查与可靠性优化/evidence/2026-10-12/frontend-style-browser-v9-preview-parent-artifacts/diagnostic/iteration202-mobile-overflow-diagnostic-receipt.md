# Iteration 202 mobile overflow diagnostic (read-only)

- Run date: 2026-10-12
- Runtime: Node 20.20.2; Playwright trace version 1.58.2
- Browser: Chromium 145.0.7632.6
- Fixture: synthetic auth/workspace responses on the existing local Vite preview at http://127.0.0.1:4187
- Reproduction source: /tmp/iteration202-mobile-overflow-diagnostic.js
- Post-settle screenshots: /tmp/iter202-mobile-diag-login.png, /tmp/iter202-mobile-diag-workspace.png

## Observed measurements

The login page was 1280px wide before resizing. Selecting the theme left an Element Plus .el-dropdown__popper in el-zoom-in-top-leave-active el-zoom-in-top-leave-to at left=1058, right=1256.59375, width 198.59375. After setViewportSize(390x844), innerWidth=390, documentElement.clientWidth=390, documentElement.scrollWidth=1257, and body.scrollWidth=390. The root width remained 1257 in resize samples 0 through 9. At sample 10 the popper was display:none, with a zero rect, and root/body scroll widths were 390; sample 11 and the later 450ms sample also stayed at 390.

The workspace page showed the same effect from the theme popper at left=889, right=1087.59375, width 198.59375. After resizing to 390px, documentElement.scrollWidth=1088 while body.scrollWidth=390; the popper remained in its leave transition through resize samples 0 through 11. After 450ms it was display:none and root/body scroll widths were both 390.

The exact failures are explained by the closing popup's old desktop position, not persistent page-content overflow. The E2E trace records setViewportSize({width:390,height:844}) at 7208.258ms, the scrollWidth evaluation at 7235.995ms (27.7ms later), and a screencast frame at 390x844. The existing threshold remains valid once the transition ends.

## Minimal test change

After clicking the theme label, wait for the theme-specific .el-dropdown__popper locator to become hidden, then keep the existing documentElement.scrollWidth <= 390 assertion. The wait should use Playwright's default assertion timeout and no fixed sleep.
