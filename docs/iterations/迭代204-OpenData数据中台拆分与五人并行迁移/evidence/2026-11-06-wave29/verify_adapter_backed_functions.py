"""Live-verify the only 8 AFI scripts whose source function an OpenData fetcher actually references.

Why these 8: an uncapped run of #286's tool over all 1057 rows finds 961 distinct resolved
source_functions, and exactly 8 of them appear in OpenData's registered akshare fetchers. Those are
the only rows for which ``REUSE_PROVIDER`` is even reachable, because the tool requires
adapter-present AND a source-verification record. So this script calls those 8 upstream functions
for real and records what came back.

Records are only written for calls that returned rows. A zero-row or failing call is reported as an
unavailability observation and deliberately does NOT become a verification record -- a record that
means "we could not get data" would inflate the numerator it is supposed to guard.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from datetime import datetime, timezone

# (function, kwargs that give it a real chance of returning rows)
# kwargs are taken from inspect.signature on the installed build; two earlier failures here were
# my wrong arguments, not the sources, so the signatures are part of the record.
TARGETS = [
    ("bond_zh_hs_cov_daily", {}),
    ("fund_etf_hist_em", {"symbol": "159915", "period": "daily",
                         "start_date": "20240101", "end_date": "20240201", "adjust": ""}),
    ("option_sse_daily_sina", {}),
    ("futures_zh_daily_sina", {"symbol": "AU2402"}),
    ("index_zh_a_hist", {"symbol": "000300", "period": "daily",
                        "start_date": "20240101", "end_date": "20240201"}),
    ("stock_financial_analysis_indicator_em", {"symbol": "301389.SZ"}),
    ("stock_financial_report_sina", {"stock": "sh600600", "symbol": "利润表"}),
    ("stock_history_dividend_detail", {"symbol": "000002", "indicator": "分红"}),
]


def main() -> None:
    import akshare as ak

    version = getattr(ak, "__version__", "?")
    verified, unverified = [], []
    for name, kwargs in TARGETS:
        fn = getattr(ak, name, None)
        entry = {"source_function": name, "akshare_version": version,
                 "params": kwargs, "observed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if fn is None:
            entry["status"] = "ABSENT_IN_INSTALLED_AKSHARE"
            unverified.append(entry)
            continue
        try:
            entry["signature"] = str(inspect.signature(fn))[:180]
        except Exception:  # noqa: BLE001
            pass
        t = time.time()
        try:
            df = fn(**kwargs)
            rows = int(getattr(df, "shape", (0,))[0])
            entry.update(rows=rows, cols=[str(c) for c in list(getattr(df, "columns", []))[:8]],
                         secs=round(time.time() - t, 2))
            if rows > 0:
                entry["status"] = "verified_nonempty"
                verified.append(entry)
            else:
                entry["status"] = "empty_frame_so_not_a_verification"
                unverified.append(entry)
        except Exception as exc:  # noqa: BLE001
            entry.update(status=f"call_failed:{type(exc).__name__}", error=str(exc)[:140],
                         secs=round(time.time() - t, 2))
            unverified.append(entry)
        time.sleep(1.0)

    export = {
        "records": [
            {
                "source_function": v["source_function"],
                "verified_at_utc": v["observed_at_utc"],
                "akshare_version": v["akshare_version"],
                "params": v["params"],
                "rows_observed": v["rows"],
                "evidence": "live akshare call from this machine, non-empty",
            }
            for v in verified
        ],
        "meaning": ("each record is one real call that returned rows; REUSE_PROVIDER in #286 reads only "
                    "source_function + verified_at_utc, the extra fields are so an auditor can see what "
                    "was actually observed"),
    }
    print(json.dumps({"verified": export["records"], "not_verified": unverified},
                     ensure_ascii=False, indent=2))
    with open("/tmp/it204/sv/source_verification_export.json", "w", encoding="utf-8") as fh:
        json.dump(export, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())
