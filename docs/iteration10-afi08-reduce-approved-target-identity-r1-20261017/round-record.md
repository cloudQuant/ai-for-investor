# AFI08 approved-target SERVICE identity boundary — R1

- Repository/branch: `D:/source_code/ai-for-investor`, `dev`.
- Source base: `c53beefb38ac37555ea39aa979d0f7ff7d49222d`.
- Scope: `src/backend/app/services/strategy_target_approvals.py` and the new `src/backend/tests/test_strategy_reduction_identity_boundary.py`.

Target creation and approval remain restricted to `application_client`. The persisted-target reader now also permits a `service` identity to reserve, resolve, and consume an existing target only when the stored target is `position_effect=CLOSE` and `reduce_only=true`. Existing owner, principal, actor, delegate, exact wire-scope, approval-version, and target-digest checks remain in force. This closes the role mismatch between the persisted human-approved target and the trusted Execution SERVICE consumer; it does not add a tenant model or broaden target creation.

Acceptance used the repository AFI virtual environment (Python 3.12.10), normal `conftest.py`, UTF-8 mode, and the existing local SDK source roots. Collection found one node. The focused node `tests/test_strategy_reduction_identity_boundary.py::test_service_identity_can_consume_only_exact_persisted_close_target` passed (1 passed, 4.98s, exit 0). The test uses actual SQLite persistence for owner, strategy/version, policy, approval, operation reservation, current-state resolution, and consumption. It checks application-created CLOSE use by SERVICE, same-identity consumption replay, rejection of SERVICE target creation, rejection of OPEN without an operation reservation, and rejection of altered actor, delegate, or run scope. No provider action occurs.

Independent static review by `audit_afi_remaining_cases` returned GO_STATIC for the exact source and test pins. The reviewer did not run tests or a Host. Evidence is local synthetic SQLite identity-boundary coverage only; no HTTP/ServiceHost, provider, cross-tenant model, real-account, or formal AFI08 acceptance is claimed. The containing scoped source commit is recorded by Root at delivery.
