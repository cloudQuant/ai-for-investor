"""Build a *draft, unsigned* AC11 review file for the highest-evidence dispositions.

`assign_script_dispositions.py` defines `assigned` as: a named human wrote
{"reviewer","decision":"approve","disposition"==proposed,"file_sha256"} into --review-file.
Nothing here is signed. It only assembles the rows whose evidence is already strong enough that
the remaining work is a human yes/no per disposition, and it records why each row is in the batch.
"""

import csv
import hashlib
import json
import pathlib
from datetime import datetime, timezone

AFI = pathlib.Path("/home/yun/Documents/ai-for-investor")
LEDGER = pathlib.Path("/tmp/it204/ac11-out/script_disposition_ledger.csv")
OUT = pathlib.Path("/tmp/it204/ac11-review-batch02.draft.json")

# The 11 scripts the owner-side evidence artifact calls mapped_confirmed: catalog
# REGISTERED_FETCHER_MATCH *and* an OpenData provider model file actually read.
MAPPED_CONFIRMED = {
    "bond_zh_hs_cov_daily", "daily_market_data", "fund_etf_hist_em", "futures_zh_daily_sina",
    "index_constituent_weights_csindex", "index_zh_a_hist", "option_sse_daily_sina",
    "stock_financial_analysis_indicator_em", "stock_financial_report_sina",
    "stock_history_dividend_detail", "stock_zh_a_hist",
}

# The 7 scripts whose registrations name a file that exists in no ref; their 50 armed tasks were
# deactivated by owner ruling at 2026-11-06 13:47:56 UTC after 100% post-repair failure.
GHOST_SCRIPTS = {
    "fund_monetary_income_history", "forex_hist_sina", "fund_reviewed_unit_nav_history",
    "etf_realtime_quote_sina", "cffex_option_daily_history", "commodity_option_daily_history",
    "etf_option_daily_history",
}

rows = list(csv.DictReader(LEDGER.open(encoding="utf-8-sig")))
by_stem = {pathlib.Path(r["path"]).stem: r for r in rows}

entries, skipped = [], []


def sha256_of(relpath: str) -> str:
    return hashlib.sha256((AFI / relpath).read_bytes()).hexdigest()


def add(stem, reason):
    r = by_stem.get(stem)
    if r is None:
        skipped.append((stem, "not in the 1057-script ledger"))
        return
    proposed = r["disposition"]
    try:
        digest = sha256_of(r["path"])
    except OSError as exc:
        skipped.append((stem, f"unreadable: {exc}"))
        return
    matches = digest == r.get("sha256")
    inventory_stale = str(r.get("inventory_sha_matches_current", "")).lower() in ("no", "false")
    entries.append({
        "script_id": stem,
        "path": r["path"],
        "proposed_disposition": proposed,
        "reviewer": "",            # <-- deliberately empty: an agent cannot sign this
        "decision": "",            # <-- owner writes "approve" or "reject"
        "disposition": "",         # <-- owner confirms/edits the §5 disposition
        "file_sha256": digest,
        "recomputed_matches_ledger": matches,
        "inventory_sha_matches_current": not inventory_stale,
        "batch_evidence": reason,
    })


for stem in sorted(MAPPED_CONFIRMED):
    add(stem, "owner evidence: catalog REGISTERED_FETCHER_MATCH + OpenData provider model file read")

for stem in sorted(GHOST_SCRIPTS):
    add(stem, "registered but module_path exists in no git ref; 50 armed tasks failed 100% post-repair; "
              "tasks deactivated by owner ruling 2026-11-06 13:47:56 UTC")

for r in rows:
    if r["disposition"] == "HELPER_ONLY":
        add(pathlib.Path(r["path"]).stem, "inventory static_role=helper_review_only (no task should exist)")

payload = {
    "status": "DRAFT-UNSIGNED",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "tool": "build_ac11_review_batch02.py (this script), reading assign_script_dispositions.py output",
    "meaning": ("An assignment requires a named human reviewer, decision=approve, and disposition "
                "equal to the proposal, for this exact file sha256. Reviewer/decision/disposition "
                "fields here are intentionally blank."),
    "blocking_caveat": (
        "891 of 1057 ledger rows have inventory_sha_matches_current=no, and 23 of those disagree with "
        "no attributable commit, which shows the inventory CSV was generated against a dirty tree. "
        "Signing is therefore evidence about today's tree, not about the CSV's recorded hashes; the CSV "
        "must be re-frozen from a clean tree before these signatures are cited as AC01 baseline evidence."),
    "entries": entries,
    "skipped": skipped,
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
signable = [e for e in entries if e["inventory_sha_matches_current"]]
print(f"entries: {len(entries)}  with inventory hash still matching today's tree: {len(signable)}  skipped: {len(skipped)}")
for e in entries[:6]:
    print(f"  {e['script_id']:<34} {e['proposed_disposition']:<22} inv_ok={e['inventory_sha_matches_current']}")
for stem, why in skipped:
    print(f"  SKIPPED {stem:<34} {why}")
print("written:", OUT)
