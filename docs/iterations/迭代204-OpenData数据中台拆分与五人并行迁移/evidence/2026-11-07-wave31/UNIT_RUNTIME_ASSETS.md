# AC01 runtime-asset surface, re-measured 2026-11-07T19:07Z

Instrument `unit_runtime_asset_audit.py` (read-only: `systemctl --user show`, `os.path`,
`git cat-file -e`, `git rev-list --all`). It answers three questions per `ExecStart` target:
on disk? in `origin/dev`? in **any** ref?

## Result

| | |
|---|---|
| units audited | 10 |
| units whose script is missing on disk | **8** |
| unique missing script paths | **7** |
| units executing **unversioned** source (on disk, in no ref) | **0** |
| highest restart counter | **7,895** (`ai-for-investor-etf-nav-backfill@.service`, `activating`) |

### The 7 paths that exist nowhere

`src/backend/scripts/ops/` — `run_dce_browser_capture.sh`, `run_dce_option_recovery.sh`,
`run_etf_nav_shard.sh`, `run_option_history_loop.sh`, `policy_expiry_watchdog.py`,
`backfill_stock_amount_sina.py`, `run_stock_tail_slices.sh`.

### What each unit does about it

| unit | state | what it means |
|---|---|---|
| dce-browser-capture | failed | exit-code, never starts |
| dce-option-daily | failed | exit-code |
| dce-option-recovery | inactive | `success` result but no file — it never really ran |
| etf-nav-backfill@ | **activating** | crash loop, `NRestarts=7895`, `RestartSec=30` |
| option-history | inactive | disabled |
| policy-expiry-watchdog | failed | exit-code |
| stock-amount-daily | failed | exit-code |
| stock-tail-daily | failed | exit-code |

## Why this is the honest shape of the AC01 gap

The wave-29 wording ("9 live files not in any ref") could be read as *unreviewed code running in
production*. This measurement separates the two defects and shows the opposite: **no live unit
executes source that is absent from git**. The real defect is availability — 8 units are pointed
at files that were never committed (or were deleted), so they can never run, and one of them
retries every 30 s forever (7,895 restarts).

The `.venv/bin/python` and `node_modules/vite/bin/vite.js` tokens are interpreter/binary paths and
are excluded from the source-asset count; counting them would inflate "unversioned" to 10 units
and say something false.

## What would close it

Either commit the 7 scripts (they are the assets the units were written for) or repoint/disable
the 8 units. Both are owner/ops decisions — the files cannot be reconstructed from any ref, and
writing new ones would invent behavior, not recover it. Until then AC01's runtime-asset half stays
open with this exact list.
