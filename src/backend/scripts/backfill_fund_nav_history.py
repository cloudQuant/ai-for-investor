"""Resumable fund NAV history backfill from the East Money F10 lsjz endpoint.

Why this exists instead of reusing funds/weekly/etf_fund_hist_em.py: that script calls
akshare's fund_etf_fund_info_em, which re-requests page 1 just to learn the page count
(28k wasted requests over a full universe) and truncates the code list to
DEFAULT_ETF_HIST_CODE_LIMIT.

The endpoint caps every response at 20 rows (pageSize>200 is silently rejected with
TotalCount=0), so one cold fund costs nav_days/20 requests. Progress is therefore read
back from the warehouse -- each fund resumes from its own MAX(VALUE_DATE) -- which makes
the sweep safe to interrupt and re-run.

Usage:
    python scripts/backfill_fund_nav_history.py --limit 40 --concurrency 4   # calibrate
    python scripts/backfill_fund_nav_history.py --concurrency 4              # full sweep
"""

from __future__ import annotations

import argparse
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime

import pymysql
import requests

F10_URL = "https://api.fund.eastmoney.com/f10/lsjz"
PAGE_SIZE = 20
MAX_RETRIES = 3
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def warehouse_config() -> dict:
    raw = open(ENV_PATH, encoding="utf-8").read()
    match = re.search(r"^AKSHARE_DATA_DATABASE_URL=(.+)$", raw, re.M)
    if not match:
        raise SystemExit(f"AKSHARE_DATA_DATABASE_URL not found in {ENV_PATH}")
    parsed = urllib.parse.urlparse(match.group(1).strip())
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": urllib.parse.unquote(parsed.password or ""),
        "database": "akshare_data",
        "charset": "utf8mb4",
        "autocommit": False,
    }


def connect(cfg: dict):
    return pymysql.connect(**cfg)


def dashed(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def refresh_universe(cfg: dict) -> list[str]:
    """FUND_BASIC_INFO_EM is a snapshot of akshare's live fund list and goes stale
    (it was 3.5 months behind when first measured), so pull the live list."""
    import akshare as ak

    df = ak.fund_name_em()
    conn = connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO FUND_BASIC_INFO_EM
                    (R_ID, FUND_CODE, FUND_SHORT_NAME, FUND_TYPE, IS_ACTIVE, DATA_SOURCE)
                VALUES (%s, %s, %s, %s, 1, '东方财富')
                ON DUPLICATE KEY UPDATE
                    FUND_SHORT_NAME = VALUES(FUND_SHORT_NAME),
                    FUND_TYPE = VALUES(FUND_TYPE),
                    IS_ACTIVE = 1,
                    UPDATEDATE = CURRENT_TIMESTAMP
                """,
                [
                    (str(r["基金代码"]), str(r["基金代码"]), str(r["基金简称"]), str(r["基金类型"]))
                    for _, r in df.iterrows()
                ],
            )
        conn.commit()
    finally:
        conn.close()
    codes = sorted({str(c).zfill(6) for c in df["基金代码"].tolist()})
    log(f"universe refreshed from fund_name_em(): {len(codes)} codes")
    return codes


def load_universe(cfg: dict) -> list[str]:
    conn = connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT FUND_CODE FROM FUND_BASIC_INFO_EM ORDER BY FUND_CODE")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def load_watermarks(cfg: dict, table: str) -> dict[str, str]:
    conn = connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT FUND_CODE, MAX(VALUE_DATE) FROM `{table}` GROUP BY FUND_CODE")
            return {code: d.isoformat() for code, d in cur.fetchall() if d}
    finally:
        conn.close()


def _num(value):
    if value in (None, "", "---"):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def fetch_nav(code: str, start: str, end: str) -> list[tuple]:
    """Pages the F10 endpoint. Returns (VALUE_DATE, unit, accum, growth, purchase, redemption)."""
    sess = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 Chrome/80.0.3987.149 Safari/537.36",
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
    }
    params = {
        "fundCode": code,
        "pageIndex": "1",
        "pageSize": str(PAGE_SIZE),
        "startDate": start,
        "endDate": end,
    }
    out: list[tuple] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        params["pageIndex"] = str(page)
        params["_"] = str(round(time.time() * 1000))
        payload = sess.get(F10_URL, params=params, headers=headers, timeout=45).json()
        total = int(payload.get("TotalCount") or 0)
        items = ((payload.get("Data") or {}).get("LSJZList")) or []
        if page == 1:
            total_pages = -(-total // PAGE_SIZE)
        for it in items:
            vdate = it.get("FSRQ")
            if not vdate:
                continue
            out.append(
                (
                    vdate,
                    _num(it.get("DWJZ")),
                    _num(it.get("LJJZ")),
                    _num(it.get("JZZZL")),
                    (it.get("SGZT") or "")[:50] or None,
                    (it.get("SHZT") or "")[:50] or None,
                )
            )
        page += 1
    sess.close()
    return out


def save_rows(cfg: dict, table: str, code: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn = connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO `{table}`
                    (R_ID, REFERENCE_CODE, REFERENCE_NAME, FUND_CODE, VALUE_DATE,
                     UNIT_NET_VALUE, ACCUMULATED_NET_VALUE, DAILY_GROWTH_RATE,
                     PURCHASE_STATUS, REDEMPTION_STATUS, IS_ACTIVE, DATA_SOURCE)
                VALUES (%s, 'ETF_FUND_HIST', '基金历史净值数据表(东方财富)', %s, %s,
                        %s, %s, %s, %s, %s, 1, '东方财富')
                ON DUPLICATE KEY UPDATE
                    UNIT_NET_VALUE = VALUES(UNIT_NET_VALUE),
                    ACCUMULATED_NET_VALUE = VALUES(ACCUMULATED_NET_VALUE),
                    DAILY_GROWTH_RATE = VALUES(DAILY_GROWTH_RATE),
                    PURCHASE_STATUS = VALUES(PURCHASE_STATUS),
                    REDEMPTION_STATUS = VALUES(REDEMPTION_STATUS),
                    IS_ACTIVE = 1,
                    UPDATEDATE = CURRENT_TIMESTAMP
                """,
                [(f"{code}_{r[0]}", code, r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass
class Stats:
    done: int = 0
    rows: int = 0
    empty: int = 0
    failures: int = 0
    started: float = time.time()

    def bump(self, **kw) -> None:
        with _print_lock:
            for key, val in kw.items():
                setattr(self, key, getattr(self, key) + val)


def process(cfg: dict, table: str, code: str, start: str, end: str, stats: Stats) -> int:
    err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rows = fetch_nav(code, start, end)
            written = save_rows(cfg, table, code, rows)
            stats.bump(done=1, rows=written, empty=1 if not rows else 0)
            return written
        except Exception as exc:  # noqa: BLE001 -- one bad code must not kill the sweep
            err = f"{type(exc).__name__}: {str(exc)[:70]}"
            time.sleep(2 * attempt)
    stats.bump(done=1, failures=1)
    log(f"FAIL {code} after {MAX_RETRIES} attempts -- {err}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-table", default="ETF_FUND_HIST_EM")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="stop after N codes (calibration)")
    ap.add_argument("--from-date", default="20000101", help="cold-start depth, YYYYMMDD")
    ap.add_argument("--codes", nargs="*", default=None, help="explicit codes; skips the universe")
    ap.add_argument("--codes-file", help="one code per line; skips the universe")
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--report-every", type=int, default=25)
    args = ap.parse_args()

    cfg = warehouse_config()
    if args.codes:
        codes = list(args.codes)
    elif args.codes_file:
        codes = [ln.strip() for ln in open(args.codes_file, encoding="utf-8") if ln.strip()]
    elif args.refresh_universe:
        codes = refresh_universe(cfg)
    else:
        codes = load_universe(cfg)
    marks = load_watermarks(cfg, args.target_table)
    end = date.today().isoformat()
    cold_start = dashed(args.from_date)

    pending = list(codes)
    if args.limit:
        pending = pending[: args.limit]

    log(
        f"universe={len(codes)} with_history={len(marks)} to_process={len(pending)} "
        f"table={args.target_table} concurrency={args.concurrency} end={end}"
    )

    stats = Stats()
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(
                process, cfg, args.target_table, code, marks.get(code, cold_start), end, stats
            ): code
            for code in pending
        }
        for i, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if i % args.report_every == 0:
                elapsed = time.time() - started
                rate = i / elapsed
                remaining = (len(futures) - i) / rate if rate else 0
                log(
                    f"progress {i}/{len(futures)} rows={stats.rows} "
                    f"empty={stats.empty} fail={stats.failures} "
                    f"{rate * 60:.1f} codes/min eta={remaining / 3600:.1f}h"
                )

    elapsed = time.time() - started
    per = elapsed / max(stats.done, 1)
    log(
        f"DONE codes={stats.done} rows={stats.rows} empty={stats.empty} "
        f"failures={stats.failures} elapsed={elapsed:.1f}s"
    )
    if args.limit:
        log(
            f"CALIBRATION {per:.2f}s/code (c={args.concurrency}) -> "
            f"all {len(codes)} codes ~= {len(codes) * per / 3600:.1f} wall-clock hours"
        )
    return 1 if stats.failures and stats.failures == stats.done else 0


if __name__ == "__main__":
    raise SystemExit(main())
