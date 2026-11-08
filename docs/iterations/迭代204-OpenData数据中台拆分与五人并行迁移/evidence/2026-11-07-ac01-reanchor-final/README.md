# AC01 inventory re-anchor — final run on `74e2a0570a`

The CSV carried a per-file `source_sha256` that had not been regenerated since the inventory was
built on 2026-10-26, so AC01's "no unexplained item" could not be answered from the tree. The
generator (`scripts/ops/refresh_script_migration_inventory.py`, #313) now exists in the repo and is
run here against the tree that contains every collection-plane change (#314, #319 included).

| step | result |
|---|---|
| check before | `content_drift=891, ghost_registration=9, in_sync=166`, **0 unexplained**, gate 166/166 |
| emit | 902 rows rewritten; only `source_sha256`, `static_role`, and the `AST静态标记=` prefix of `notes` change |
| check after | `in_sync=1057, ghost_registration=9`, **0 unexplained**, gate **1057/1057 (PASS)** |

`check-before.json`, `emit.json`, `check-after.json` are the tool's own machine-readable summaries.

## Boundary

This closes the "recorded anchor does not match the tree" half of AC01's anchor gap. It does not
touch the other two open halves: the 7 systemd scripts that exist in no ref, and the
per-instrument interior gaps that need a source-native calendar.
