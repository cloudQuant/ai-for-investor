# Iteration 10 AFI10 AI service-read bridge R1

- Base: `dev` at `d7b67f920980822fd1fd8275866b511ac6fb052e`.
- Scope: AI account context reads the authenticated subject's configured Service Read grant and accepts only fresh, complete, finite provider observations. Live asset metadata comes from local verified specs; live order submission remains unavailable. Paper selection and ordinary research remain available.
- Focused evidence: backend AI-trading tests, selector/config and asset-metadata regressions; frontend AITradingPage tests and typecheck; Ruff and diff checks passed. Independent review: `GO_STATIC` on the final candidate pins.
- Evidence level: local synthetic tests and static review only. No real provider/account or live-order acceptance; Iteration 10 formal status is unchanged.
