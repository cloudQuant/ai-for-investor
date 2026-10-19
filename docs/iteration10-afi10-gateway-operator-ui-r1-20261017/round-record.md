# AFI10 trusted Gateway operator UI R1

- Repository: `ai-for-investor`, branch `dev`; parent HEAD `5c650c0bebb7fd982c7843c43708c56d701bb4b3`.
- Scope: add a GatewayStatusPage panel and API client for the existing owner-authorized `/service-gateway/operators` endpoints. The browser selects only server-listed profiles and granted operations; operation requests contain no credentials or scope. Page mount reads list/status only. The existing manual Gateway controls remain a separate compatibility path, clearly labeled as legacy.
- Acceptance: after static review identified a refresh/action race, refresh is disabled and guarded during owner actions; actions remain locked while a refresh is pending, so an older `new` result cannot arrive after a start result. Nullable cleanup counts display as unknown. Focused frontend tests 18 passed; `vue-tsc --noEmit`, scoped ESLint, and scoped `git diff --check` passed.
- Evidence limit: local UI/API-mock checks only. No browser session, real deployment profile, provider, account, or full AFI10 retirement was tested.
