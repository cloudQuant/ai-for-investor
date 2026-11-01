# AFI10 quote status reads no longer start legacy market consumers

- Repository/branch: `D:\source_code\ai-for-investor`, `dev`; base HEAD `ff592288ce48bd1bef05a23db1e161fd8589ebba`.
- Scope: `QuoteService.get_data_sources()` now reports existing gateway/workspace status without creating a `ZmqTickReceiver` or issuing `subscribe`. It still uses the existing gateway readiness check, which can send `ping`; this round does not establish a network-free status read. Quote reads remain responsible for demand-driven unconfigured legacy subscriptions during this transition; configured service-v2 behavior is unchanged.
- Acceptance: local focused author tests on the AFI backend venv (Python 3.12.10, pytest 9.1.1). First invocation: two status-path tests passed; the new quote-read guard test failed because the test recorder included a harmless empty subscribe call. After changing only that recorder to capture nonempty subscriptions, the affected quote-read node passed. Targeted Ruff passed. This is local unit evidence, not Host, provider, or AFI10 acceptance.
- Review: independent static review returned GO on the three source/test pins; it ran no tests and made no edits.
- Remaining boundary: legacy quote/chart transport for unconfigured online symbols is not retired by this round.
