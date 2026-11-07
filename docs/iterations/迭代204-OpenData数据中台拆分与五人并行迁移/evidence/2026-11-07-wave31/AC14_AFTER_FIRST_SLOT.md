# AC14 after-image, first post-deploy slot (2026-11-07T20:03Z)

`ac14_before_after.py --task-id 1049 --since 2026-11-07T19:26:47Z` (the restart instant).

| | before (11-06T19:00Z .. 11-07T19:08Z) | after (first slot) |
|---|---|---|
| runs | 25 | 1 |
| ≥599 s timeouts | 24 | **0** |
| completed | 0 | **1** |
| duration | 600 s (timeout) | **25 s** |
| rows written | 0 | **+46** (1,715,064 → 1,715,110) |
| error | platform timeout | none |

The run at 20:03:00Z finished at 20:03:25Z. That is exactly the shape #316 predicted (tail first,
backfill after), and it is the first time this task has completed since 2026-11-05 00:03.

**One slot is not AC14.** AC14 is a natural-cycle item; the after-image needs consecutive slots.
What this establishes is that the deployed code no longer times out on the first opportunity —
not that coverage has accrued.
