# AFI09 legacy Gateway manual-connect and restore migration R1

Repository: `D:\source_code\ai-for-investor`, branch `dev`.

This round retires manual credential-based Gateway connect/disconnect and boot restore. The legacy endpoints return `LEGACY_GATEWAY_MIGRATION_REQUIRED` before normalizing, reading, persisting, or passing credentials to a runtime. Startup keeps saved legacy files byte-for-byte and skips deserializing/replaying them. Surviving legacy live instances are not rebuilt into the retired manager-owned Gateway runtime; simulation and ServiceExecutionSession remain separate. The owner-facing migration projection lists only exact keys explicitly mapped by the requesting owner’s authorized Service Gateway profile. The UI presents those mappings and authorized profile controls without exposing legacy credential actions or starting a profile automatically.

Scope is the reviewed 21-path candidate: 19 existing paths plus deletion of `GatewayConnectDialog.vue` and its test. In `manager.py`, only manual connect/disconnect and restore hunks are included; the separate AI-paper profile launch hunks are excluded. The reviewed manager checkout pin also contained those disjoint hunks, so the selected commit hunk is intentionally narrower than the reviewed file blob.

Independent static review: GO_STATIC from `audit_afi_remaining_cases`; 19 existing-file pins and two expected deletions matched at source HEAD `b59b05738fc2418891069fb90882b668e0a94a65`, with an empty index. The AFI10 quote-retirement commit `f888ead54b79cef704039e09135f896c80295ec7` is a disjoint parent advance; candidate pins were rechecked unchanged before delivery.

Author-reported focused checks: frontend panel/API tests 14 passed; frontend typecheck passed; Ruff passed. Three targeted backend migration/restore cases passed across focused invocations after correcting a test fixture method-name typo; this was not a single three-case run. No Host, account, or real credential test was run. These checks and the static review do not establish formal MIG01 completion or real-account acceptance.

The formal MIG01 closure remains incomplete: old Base Gateway package/runtime and remaining legacy imports/exports require the separate quote/history and provider-factory migration work. This round does not delete the saved legacy records or claim that an unmapped record exists.