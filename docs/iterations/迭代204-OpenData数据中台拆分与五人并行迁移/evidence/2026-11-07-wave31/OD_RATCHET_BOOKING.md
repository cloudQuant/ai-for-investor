# OD acceptance ratchet, booked from CI run 42404291048 (post-#202)

Dispatch: `workflow_dispatch` on `dev` with `sync_acceptance_ratchet=true`, 2026-11-07T19:03:03Z.
Run **42404291048** — `completed / success` at 19:35:50Z, head `c02b136ab5`. Artifact
`acceptance-gate-ratchet`, written by `python scripts/quality/acceptance_item_probe.py --sync-ratchet`
(so it measured in the job's environment instead of re-pinning a stale reading).

## The 8 entries, all `ledger_state: proven`

| item | family | digest |
|---|---|---|
| AC-1\|08 | stale-proof | `9063a0a4b26c6c7049e1da66df25ce184deb108dde729e8cfb7ae5d8a9bb7cbd` |
| AC-1\|10 | stale-proof | `3f4d6caf07220b18b3a1caa8610a8a02c3c1cfffa6a853bff2e5f601b4557915` |
| AC-5\|03 | stale-proof | `c278235ccafb68ae322663fa2a85a27577ceadd63dc7aa685a661b95565c907c` |
| AC-11\|04 | stale-proof | `228b084a4d354bdee19c152cf130a4177717d545ed165bacc03fe100ee6e5077` |
| AC-16\|05 | stale-proof | `5c4feae16d3d6088840614d88d70147f036a923f153628d3a005ea9ec2069e48` |
| AC-16\|06 | stale-proof | `40273932e1c3adf7bbd231874712471aaa32545412a5a6acc0da36fae0a27788` |
| AC-17\|03 | stale-proof | `cddc75eaaf315b73db28e40dc31f049f1ecfe42f3fe5578f33213a23a33e514e` |
| AC-17\|06 | stale-proof | `28168a2f4db59c3f8744c5bb777dad322e3d4f7debefe91d77c4e98bb9cea6ee` |

## What changed versus the artifact that must not be booked

Wave 29 refused to book the 8-pin artifact from run 42228207697 because it contained **AC-5|07**,
whose only failing facts were `scan-stale` / `triage-stale` — a 24-hour rolling expiry
(`MAX_EVIDENCE_AGE`), not a new finding. PR #202 moved the rebuild ahead of the booking step.
This artifact is the result: **AC-5|07 is absent**, and `AC-1|08` is present with a fresh
stale-proof digest.

The debt-table prediction was "6 pins + AC-1|08"; the actual set is 7 + AC-1|08 = 8, because
AC-1|10 and AC-5|03 are also in it. The record states the measured set, not the prediction.

## Boundary

This closes the booking action for AC-5|07's stale artifact. It does **not** change any CODE /
REAL_SOURCE / DEPLOYMENT / NATURAL_CYCLE verdict, and it is not evidence for iteration-204's own
acceptance items — it is the OD gate ledger's state on `c02b136ab5`.
