# AFI07 approved strategy target: proposed contract

**Date:** 2026-10-16  
**Status:** frozen v1 cross-boundary contract for AFI/Execution implementation; the database slice under development does not complete AFI07  
**Scope:** one owner, one configured account, one strategy, one approved single-order target. This is a bounded AFI07 slice. It does not complete AFI07, authorize group-leg changes, or establish that any displayed portfolio is creditable.

## Current boundary

AFI currently exposes `POST /service-orders/manual`. Its request rejects extra fields, and the route derives owner, service identity, account and manual book from the authenticated user and server configuration. `ServiceOrderOperation` durably maps a scoped idempotency key and request digest to an intent ID. This manual path should remain a distinct operation.

The current order-submit binding is manual-book scoped. The SDK `orders.submit` contract has ordinary order terms but no typed approval reference, target digest, approval version, or trusted approval-verification input. Therefore AFI cannot make an approved-target path safe by adding HTTP fields alone. The Execution owner must verify the approval facts against a trusted server-side authority before accepting the intent.

Research approvals are scoped to research artifacts and the `research:approve` capability. They are not trading approvals and must not be reused. AFI02 composition membership versions and hashes may be included as frozen target context, but those projections are display-only, non-additive, and non-creditable; they do not grant order authority or establish account value.

## Proposed approval and target record

Persist a trade-specific approval separately from research approvals and AI run logs. Suggested immutable approval fields:

- Identity: `approval_ref`, `owner_subject`, configured `principal_ref`, `actor_ref`, and bounded `delegate_ref`.
- Scope: `account_ref`, `execution_domain_ref`, `strategy_ref`, configured `scope_ref`, and the immutable strategy version.
- Optional composition binding: `portfolio_ref`, `membership_version`, and `membership_sha256`, revalidated as context only. Composition membership never substitutes for account/strategy authorization.
- Target: canonical schema version, frozen target reference/version, canonical target digest, and explicit instrument identity and order terms.
- Limits and policy: quantity/notional ceiling, permitted side and position effect, price bounds where applicable, and the AFI approval/eligibility policy reference/version/digest that governed this decision. These fields do not identify the live Risk policy.
- Decision: state (`PENDING`, `APPROVED`, `REJECTED`, `REVOKED`, `EXPIRED`, or `CONSUMED`), authenticated decider identity, decision time, expiry, revocation actor/time/reason, and monotone record version.
- Use: the accepted `intent_id` and canonical submitted-intent digest, if consumed. Keep an append-only decision/revocation/use audit or equivalent durable history; never delete a consumed or revoked record to make it reusable.

Approval is owner-, actor-, delegate-, account-, strategy-, scope-, target-, and AFI approval-policy-version specific. Only a currently authorized human/API principal may decide or revoke it. The server derives the decider from the authenticated token and authorization policy; a request's `approver`, actor, delegate, account, strategy, scope, digest, or “approved” boolean is never authoritative.

## Canonical target and digest

Define a versioned canonical JSON representation before implementing either side. It must use sorted keys, fixed UTF-8 encoding, normalized enum values, and decimal strings for quantities/prices; reject floats, non-finite values, unknown fields, and ambiguous instrument aliases. Hash the exact canonical bytes with SHA-256.

The digest should cover every fact that could change the approved order meaning: owner and trusted actor/delegate context; account, execution domain, scope, strategy and strategy version; optional composition membership version/hash; full instrument key; side, position effect, order type, quantity, limit/price bounds, time-in-force and reduce-only; target version; and AFI approval/eligibility-policy version/hash. These AFI policy fields are not a live Risk-policy binding. Current Risk policy and account admission are separate Execution/Risk facts and must be checked by that path; they are not inferred from this approval digest. UTC expiry and the approval record version are separately checked and bound by the approval authority. Any change to a covered field requires a new target digest and approval. Never resolve a mutable “latest strategy” pointer after approval and treat it as the approved version.

## HTTP and durable idempotency

Keep manual submission separate. Add a distinct approved-target submit operation (route naming can be finalized with SDK contract review). The caller should submit an `approval_ref`, expected approval version/digest, and `Idempotency-Key`; it should not resubmit mutable order terms or identity claims. AFI loads the frozen target and confirms the current JWT subject, server-mapped principal/actor/delegate, configured scope, approval state, expiry, policy version, and any bound membership version before calling Execution.

The AFI HTTP layer may persist its `Idempotency-Key` to stable-`intent_id` mapping using the existing order-operation store. It passes that stable ID unchanged to the trusted approval authority. The authority reservation takes both a code-derived `operation_key` and the caller-supplied `intent_id`; it never mints or substitutes the ID. SDK derives `operation_key` as SHA-256 of canonical v1 `{approval_ref,approval_version,target_sha256,intent_id,principal_ref,identity,wire_scope,owner_subject}`. The authority atomically binds that key and intent to the approval reference/version and target digest. An identical retry returns the same binding; a changed key, approval, target, identity, scope, or intent returns conflict. The raw HTTP idempotency key is not sent to Execution. The operation table is an idempotency map, not a second order ledger; Execution’s journal remains authoritative for order state and final facts.

Reservation is not authorization and is revocable. A new reservation checks that the approval is still approved and unexpired. An exact existing reservation may return its frozen target and `intent_id` after later expiry or revocation so Execution can reconstruct the same request and return its durable result; that lookup is not permission to dispatch. Revocation and first consumption use a versioned compare-and-swap on the same durable approval row. If revocation commits first, consume is denied; if consume commits first, revocation reports that the approval is already consumed.

The dispatch sequence is: Execution durably records `DISPATCHING` for the stable intent; its pre-dispatch hook asks AFI to consume the exact approval/target/intent binding; only `CONSUMED_NEW` continues to Basic admission, Risk claim, writer-lease recheck, and provider dispatch. `ALREADY_CONSUMED` is evidence for reconciliation, never a new dispatch grant. A definitive consume denial blocks the intent before the Risk claim. A lost/ambiguous consume reply is `UNKNOWN` and must not be automatically retried or dispatched again. If consume succeeds but Basic or Risk later rejects, the approval remains consumed and the product must report `APPROVAL_USED_NOT_DISPATCHED`; it must not report an accepted order or provider call. A previously durable Execution intent replay returns the Execution record without asking consume to authorize another provider attempt.

## Required SDK / Execution verification

Prefer a separate typed capability such as `orders.submit_approved_target` so existing manual `orders.submit` semantics do not silently change. Exact operation and resource names remain an SDK contract decision. The call may carry the approval reference/version, target digest, stable intent ID and frozen terms, but those request values are claims until Execution verifies them.

The Execution service must derive the caller principal and authorized service identity from the authenticated transport/Host context, then validate against a trusted, code-owned approval authority or durable approval repository. A payload-only approval object, AFI-local ACL, caller-supplied actor, or unsigned digest is insufficient. The configured authority resolves the complete authenticated tuple `(principal_ref, role, actor_ref, delegate_ref, exact WireScope)` to exactly one `owner_subject` and one expected `scope_ref`; a missing or ambiguous mapping fails closed. AFI independently checks that the JWT subject matches the same trusted binding. No client field supplies the owner or trusted scope alias.

The trusted authority exposes the following persistence-backed methods behind the SDK-owned synchronous resource wrapper:

- `reserve_approved_target_operation(*, approval_ref, approval_version, target_sha256, operation_key, intent_id, owner_subject, principal_ref, expected_scope_ref, identity, wire_scope) -> ApprovedTargetOperationClaim`. It atomically binds the supplied stable ID; it does not mint one.
- `resolve_approved_target_v1(*, same_binding) -> canonical target mapping`. It is only for exact reserved-intent reconstruction, including after a later revoke/expiry; it is not dispatch permission.
- `consume_approved_target_v1(*, same_binding, intent_sha256) -> receipt mapping`. It returns `CONSUMED_NEW` or `ALREADY_CONSUMED`; the latter never authorizes dispatch.

Immediately before the consume compare-and-swap, the persistence authority calls its required `read_current_approval_state_v1` provider in the same database session/transaction. It validates current target, strategy, membership and policy versions/hashes against the frozen target. Missing, stale, malformed, or ambiguous current facts fail closed. This AFI persistence slice defines that provider boundary but does not yet connect a production strategy/membership/policy registry; until a trusted transactional provider is wired, approved-target consumption is unavailable.

The authority must establish all of the following before returning `CONSUMED_NEW`:

- approval exists and is approved, unexpired, not revoked, not already consumed by a different intent, and has the expected immutable version;
- authenticated subject/delegation is authorized for the exact account, strategy, execution domain, and operation;
- approval digest equals the canonical target/intent digest, with exact strategy/policy versions and allowed bounds;
- AFI's current approval/eligibility policy and the frozen account/strategy authorization facts match; this is not a live Risk-policy admission result. Execution performs Basic and Risk admission separately after consumption, and approval never bypasses those checks;
- the stable intent/idempotency mapping is either new or an identical replay, never a changed-content replay.

It also recomputes the canonical target digest and checks the exact stored strategy, membership, and AFI approval/eligibility-policy versions/hashes against current trusted AFI state. If current AFI policy or membership state cannot be obtained from a trusted server-side source, it must fail closed rather than treating the frozen target as proof of freshness. Live Risk-policy versioning/activation belongs to the separate Risk catalog/owner-confirmation path; AFI must not substitute its policy fields for that contract.

The operator configures the authority/resource and exact operation grant. Clients cannot choose a resource, add a grant, or turn approval checks off through YAML or wire options. Execution records the verified approval reference/version/digest with the durable intent/journal fact so later audit can reconcile the decision and accepted order.

Ordinary single-order operations must not address or mutate an accepted order group or its legs. They must not accept a group/leg selector as an alternate path, and a guessed leg ID cannot make ordinary submit/cancel act as a group operation. Group creation, leg resolution, and group disposition remain exclusively behind their separately authorized coordinator operations.

## Revocation and group follow-up

Revocation or expiry that wins before consume prevents new dispatch, even if an operation reservation exists. Once consume commits, revoking the approval is rejected; this does not prove that Execution passed Basic/Risk or that a provider was called. If a later admission stage rejects, AFI reports the consumed approval as `APPROVAL_USED_NOT_DISPATCHED`. Revocation never erases an Execution intent, reverses a fill, or proves a cancel. AFI must show outstanding/unknown state and use a separately authorized disposition path with a stable operation key and Execution-confirmed result.

AFI07 additionally requires an accepted-group revocation disposition. That is a later coordinated-group slice: a group approval/revocation must bind the group version and all legs, and only the group coordinator may stop increases or perform an allowed close/disposition. Pending, partial, unknown, and final account-confirmed outcomes must remain distinct. This single-order contract does not claim that group revocation is implemented.

## Minimal acceptance cases for this slice

Use a deterministic synthetic account/strategy and provider; do not use real accounts or credentials.

1. A valid approved target traverses HTTP → AFI owner worker → authenticated SDK/ServiceHost → Execution journal/provider once; response and journal retain owner, actor/delegate, account, strategy, approval version/digest, and stable intent ID.
2. Two AFI workers race with the same key and identical target: one durable mapping, one intent ID, at most one provider side effect. Restart AFI against the same persistent DB and replay: same intent and no second side effect.
3. Reusing that key with changed target, approval version, authority, or scope returns conflict with no provider side effect.
4. Cross-owner/account/strategy, forged actor/delegate/approver/scope, changed digest/version, expired/revoked approval, stale strategy or membership version, and out-of-bounds terms are rejected by the responsible server-side layer. In particular, transport identity and Execution-side approval verification must be observed; AFI’s own configuration is not evidence of what Execution authorized.
5. An ordinary order request cannot submit, cancel, or resolve a group leg. A separate later group test must verify accepted-group revocation and final disposition through the group coordinator.

These cases complete only the approved single-strategy target slice. Manual-order acceptance already recorded elsewhere is not rerun here. AFI07 remains open until strategy submission, approved-target submission, accepted-group revocation/disposition, and the full concurrent/restart behavior are each accepted on the normal production path.

## Current implementation boundary

The current AFI slice implements the dedicated approval/event models, migration, strict canonical-target parser, and persistence functions for approval creation, operation reservation, target reconstruction, revocation, and consume. Its focused database tests cover exact supplied `intent_id` reservation, conflicts, owner/identity/scope binding, expiry/revocation, typed consume receipts, canonical target freshness, and append-only record versions. These functions are storage components only; they are not yet exposed through an approved-target HTTP route or the AFI owner-worker SDK client.

Execution's agreed SDK contract is recorded above, but this slice does not register an SDK authority resource, add a Host grant, or perform an HTTP → SDK → ServiceHost → Execution call. The trusted current-state provider is an explicit required callback and is exercised only by synthetic tests; no production strategy/membership/policy registry is connected. Without that provider, consume fails closed. The current work therefore does not satisfy any end-to-end AFI07 acceptance case by itself.

Next implementation must add the authenticated approval/revocation API and authority wrapper, then the approved-target submit route through the normal AFI owner worker and Execution capability. Manual submission remains unchanged. A real synthetic ServiceHost test must observe authenticated actor/delegate and the Execution journal/provider result before this slice can claim the approved-target vertical path.

