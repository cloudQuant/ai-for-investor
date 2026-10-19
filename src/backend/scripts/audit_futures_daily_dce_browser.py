#!/usr/bin/env python3
"""Fetch DCE daily history through a browser page that can pass the exchange WAF.

大商所's ``dayQuotes`` endpoint answers every non-browser client with a JS challenge
page, so ``get_dce_daily`` fails for *every* date and step 1 of the futures audit can
only record DCE gaps as ``source_fetch_unavailable``. The scheduled pipeline then falls
back to Sina main-continuous codes (``A0``, ``M0``, ...), which are not contracts. A
browser that has run the challenge reaches the same feed back to 2001-01-04, so this
script is the missing leg: the page does only what a page can do, and everything else
goes through the shared audit helpers.

Usage:

    python3 scripts/audit_futures_daily_dce_browser.py plan     # what is still owed
    python3 scripts/audit_futures_daily_dce_browser.py serve    # loopback work/sink
    python3 scripts/audit_futures_daily_dce_browser.py snippet  # JS for the page console
    python3 scripts/audit_futures_daily_dce_browser.py ingest   # payloads -> database

``serve`` hands out only dates with no saved payload, so a page reload or a dropped loop
resumes where it stopped. Exit codes: 0 = no DCE gaps remain, 1 = gaps remain, 2 = fatal.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pandas as pd
from futures_data_audit_common import (
    AUDIT_DATA_SOURCE,
    DEFAULT_MARKET_START,
    LOGGER,
    MARKET_UNAVAILABLE_SYMBOL,
    SINA_FALLBACK_SOURCE,
    add_common_arguments,
    connect,
    load_calendar,
    load_daily_dates_by_market,
    load_market_dates,
    load_market_first_dates,
    load_unavailable_market_dates,
    record_unavailable_dates,
    resolve_as_of,
    setup_logging,
    write_report,
)

from app.data_fetch.scripts.futures.weekly.daily_market_data import FuturesDailyMarket

BRIDGE_DIR = Path(__file__).resolve().parents[1] / "logs" / "futures_data_audit" / "dce_bridge"
DEFAULT_PORT = 18899
DAY_QUOTES_URL = "http://www.dce.com.cn/dcereport/publicweb/dailystat/dayQuotes"
DCE_PAGE_URL = "http://www.dce.com.cn/dalianshangpin/xqsj/tjsj26/rtj/rxq/index.html"
POST_PATH_RE = re.compile(r"^/dce/(\d{8})$")

COLUMNS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "pre_settle",
    "volume",
    "open_interest",
    "turnover",
    "variety",
]

# Runs inside the DCE page. The feed throttles by answering with a body that has no
# ``data`` array, so an answer is only believed after retries.
PAGE_SNIPPET = """
(async () => {
  const api = '%(api)s';
  const sink = 'http://127.0.0.1:%(port)d';
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const state = window.__dceBackfill = {running: true, saved: 0, empty: [], failed: [], last: null};
  for (let pass = 1; pass <= 3; pass++) {
    const work = await (await fetch(sink + '/work')).json();
    const dates = work.dates || [];
    if (!dates.length) break;
    for (const iso of dates) {
      const day = iso.replace(/-/g, '');
      let payload = null;
      for (let attempt = 0; attempt < 3 && !payload; attempt++) {
        try {
          const response = await fetch(api, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({contractId: '', lang: 'zh', optionSeries: '',
                                  statisticsType: '0', tradeDate: day, tradeType: '1',
                                  varietyId: 'all'}),
          });
          const text = await response.text();
          const parsed = JSON.parse(text);
          if (Array.isArray(parsed.data)) {
            payload = text;
            if (!parsed.data.length) state.empty.push(iso);
          }
        } catch (error) { /* challenged or throttled: retry */ }
        if (!payload) await sleep(500 * (attempt + 1));
      }
      if (!payload) { state.failed.push(iso); continue; }
      const stored = await fetch(sink + '/dce/' + day, {method: 'POST', body: payload});
      if (stored.ok) state.saved++; else state.failed.push(iso + ':sink' + stored.status);
      state.last = iso;
      await sleep(120);
    }
  }
  state.running = false;
  console.log('dce bridge done', state.saved, 'saved,', state.failed.length, 'failed');
  return state;
})()
"""


def load_fallback_only_dates(conn: Any, market: str) -> set[date]:
    """Trading days whose rows came only from the Sina main-contract fallback.

    Count-based audits cannot see these: the fallback writes a steady 20 symbols a day,
    so the day looks covered while holding no contract at all.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT TRADE_DATE FROM FUTURES_DAILY_MARKET
            WHERE MARKET = %s
            GROUP BY TRADE_DATE
            HAVING SUM(DATA_SOURCE <> %s) = 0
            """,
            (market, SINA_FALLBACK_SOURCE),
        )
        return {row[0] for row in cursor.fetchall() if row[0] is not None}
    finally:
        cursor.close()


def build_work(
    expected: list[date],
    actual: set[date],
    fallback_only: set[date],
    unavailable: set[date],
) -> list[date]:
    """Dates DCE owes: absent, or present only as continuous codes, minus known dead ends."""
    owed = {day for day in expected if day not in actual} | set(fallback_only)
    return sorted(owed - set(unavailable))


def frame_for_day(day: str, rows: list[dict]) -> Any:
    """Map one dayQuotes payload onto the lowercase frame the daily-market pipeline wants."""
    records = []
    for item in rows:
        contract = item.get("contractId")
        variety_name = item.get("variety") or ""
        if not contract or "小计" in variety_name or "总计" in variety_name:
            continue
        letters = "".join(character for character in str(contract) if character.isalpha())
        records.append(
            {
                "symbol": str(contract),
                "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "settle": item.get("clearPrice"),
                "pre_settle": item.get("lastClear"),
                "volume": item.get("volumn"),
                "open_interest": item.get("openInterest"),
                "turnover": item.get("turnover"),
                "variety": letters.upper(),
            }
        )
    return pd.DataFrame(records, columns=COLUMNS)


def saved_stems(*directories: Path) -> set[str]:
    return {path.stem for directory in directories for path in directory.glob("*.json")}


def remaining_dates(work_file: Path, payload_dir: Path, ingested_dir: Path) -> list[str]:
    todo = json.loads(work_file.read_text(encoding="utf8"))
    already = saved_stems(payload_dir, ingested_dir)
    return [iso for iso in todo if iso.replace("-", "") not in already]


class BridgeHandler(BaseHTTPRequestHandler):
    state: dict[str, Path] = {}

    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome only lets a public page reach a loopback server when the preflight agrees.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        left = remaining_dates(self.state["work"], self.state["payloads"], self.state["ingested"])
        if self.path.startswith("/work"):
            match = re.search(r"limit=(\d+)", self.path)
            limit = int(match.group(1)) if match else 0
            self._send(200, {"remaining": len(left), "dates": left[:limit] if limit else left})
        elif self.path.startswith("/stats"):
            payloads = list(self.state["payloads"].glob("*.json"))
            ingested = list(self.state["ingested"].glob("*.json"))
            self._send(
                200,
                {
                    "pending_files": len(payloads),
                    "ingested_files": len(ingested),
                    "remaining": len(left),
                    "bytes": sum(path.stat().st_size for path in payloads + ingested),
                },
            )
        else:
            self._send(404, {"error": "no route"})

    def do_POST(self) -> None:  # noqa: N802
        match = POST_PATH_RE.match(self.path)
        if not match:
            self._send(400, {"error": "bad path"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            rows = json.loads(body.decode("utf8")).get("data")
        except json.JSONDecodeError:
            self._send(400, {"error": "not json"})
            return
        if not isinstance(rows, list):
            # A challenged response looks like JSON but carries no rows; refusing it keeps
            # the date in the work list instead of filing it as fetched.
            self._send(400, {"error": "no data array"})
            return
        self.state["payloads"].mkdir(parents=True, exist_ok=True)
        (self.state["payloads"] / f"{match.group(1)}.json").write_text(
            body.decode("utf8"), encoding="utf8"
        )
        self._send(200, {"date": match.group(1), "rows": len(rows)})

    def log_message(self, *args: Any) -> None:
        pass


def _dates_to_iso(dates: list[date] | set[date]) -> list[str]:
    return sorted(day.isoformat() for day in dates)


def compute_work(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    as_of = resolve_as_of(args.as_of)
    conn = connect()
    try:
        calendar = load_calendar(conn, as_of)
        first_dates = load_market_first_dates(conn)
        daily_dates = load_daily_dates_by_market(conn, as_of)
        fallback_only = load_fallback_only_dates(conn, "DCE")
        unavailable = {
            day for market, day in load_unavailable_market_dates(conn) if market == "DCE"
        }
    finally:
        conn.close()

    floor = first_dates.get("DCE") or DEFAULT_MARKET_START["DCE"]
    if args.start_date is not None and args.start_date > floor:
        floor = args.start_date
    expected = [day for day in calendar if day >= floor]
    work = build_work(expected, daily_dates.get("DCE", set()), fallback_only, unavailable)
    summary = {
        "as_of": as_of.isoformat(),
        "floor": floor.isoformat(),
        "expected_days": len(expected),
        "days_present": len(daily_dates.get("DCE", set())),
        "fallback_only_days": len(fallback_only),
        "previously_unavailable_days": len(unavailable),
        "work_days": len(work),
    }
    return _dates_to_iso(work), summary


def command_plan(args: argparse.Namespace) -> int:
    work, summary = compute_work(args)
    args.work_file.parent.mkdir(parents=True, exist_ok=True)
    args.work_file.write_text(json.dumps(work), encoding="utf8")
    report = {
        "script": "audit_futures_daily_dce_browser",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "command": "plan",
        "work_file": str(args.work_file),
        **summary,
        "work_sample": work[:20],
    }
    path = write_report(report, args.report_dir, "audit_futures_daily_dce_browser")
    LOGGER.info(
        "DCE 待补交易日 %s 天 (floor=%s 已有=%s 仅兜底=%s 已知不可得=%s) work=%s",
        summary["work_days"],
        summary["floor"],
        summary["days_present"],
        summary["fallback_only_days"],
        summary["previously_unavailable_days"],
        args.work_file,
    )
    LOGGER.info("审计报告已写入 %s", path)
    return 0 if not work else 1


def command_serve(args: argparse.Namespace) -> int:
    if not args.work_file.exists():
        LOGGER.error("没有工作清单 %s，请先运行 plan", args.work_file)
        return 2
    for directory in (args.payload_dir, args.ingested_dir):
        directory.mkdir(parents=True, exist_ok=True)
    BridgeHandler.state = {
        "work": args.work_file,
        "payloads": args.payload_dir,
        "ingested": args.ingested_dir,
    }
    left = remaining_dates(args.work_file, args.payload_dir, args.ingested_dir)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BridgeHandler)
    LOGGER.info(
        "DCE 桥接服务已启动 127.0.0.1:%s 待取=%s 天；请在浏览器打开 %s 后粘贴 snippet",
        args.port,
        len(left),
        DCE_PAGE_URL,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


def command_snippet(args: argparse.Namespace) -> int:
    print(PAGE_SNIPPET % {"api": DAY_QUOTES_URL, "port": args.port})
    return 0


def command_status(args: argparse.Namespace) -> int:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/stats", timeout=10) as response:
            print(response.read().decode("utf8"))
    except OSError as exc:
        LOGGER.error("桥接服务未在 127.0.0.1:%s 运行: %s", args.port, exc)
        return 2
    return 0


def verify_saved_days(isos: list[str]) -> int:
    """Effect check: a day counts as ingested only once the table itself shows rows for it."""
    if not isos:
        return 0
    conn = connect()
    try:
        present = load_market_dates(
            conn,
            "DCE",
            date.fromisoformat(min(isos)),
            date.fromisoformat(max(isos)),
        )
    finally:
        conn.close()
    return sum(1 for iso in isos if date.fromisoformat(iso) in present)


def command_ingest(args: argparse.Namespace) -> int:
    files = sorted(args.payload_dir.glob("*.json"))
    if not files:
        LOGGER.info("没有待入库的 DCE 报文")
        return 0

    updater = FuturesDailyMarket(logger=LOGGER)

    buffer: list[Any] = []
    batch_files: list[Path] = []
    batch_isos: list[str] = []
    saved_isos: list[str] = []
    empty_days: list[str] = []
    deferred_days: list[str] = []
    written_rows = 0
    written_days = 0
    # A young day that answers empty may only be throttled; believe it is genuinely
    # source-unavailable once it is old enough that a retry would have arrived by now.
    stale_cutoff = date.today() - timedelta(days=30)

    def flush() -> None:
        nonlocal buffer, batch_files, batch_isos, saved_isos, written_rows, written_days
        if buffer:
            frame = pd.concat(buffer, ignore_index=True)
            prepared = updater._prepare_daily_market_frame(
                frame, market="DCE", data_source=AUDIT_DATA_SOURCE
            )
            if updater._save_daily_market_frame(prepared, table_name="FUTURES_DAILY_MARKET"):
                written_rows += len(prepared)
                saved_isos.extend(batch_isos)
            else:
                LOGGER.error("DCE 报文写入失败，%s 天未落库", len(batch_files))
        written_days += len(batch_files)
        for path in batch_files:
            args.ingested_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(args.ingested_dir / path.name))
        buffer = []
        batch_files = []
        batch_isos = []

    for path in files:
        iso = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        try:
            rows = json.loads(path.read_text(encoding="utf8")).get("data") or []
            frame = frame_for_day(path.stem, rows)
        except Exception as exc:  # noqa: BLE001 - one bad payload must not stop the batch
            LOGGER.warning("跳过 %s: %s", path.name, exc)
            shutil.move(str(path), str(args.ingested_dir / path.name))
            continue
        if frame.empty:
            if date.fromisoformat(iso) > stale_cutoff:
                deferred_days.append(iso)
                continue  # left in the payload dir so a later run retries it
            empty_days.append(iso)
        else:
            buffer.append(frame)
            batch_isos.append(iso)
        batch_files.append(path)
        if len(batch_files) >= args.batch:
            flush()
    flush()
    if deferred_days:
        LOGGER.warning("近期空报文暂不认定不可得，留待下次重试: %s 天", len(deferred_days))

    verified_days = verify_saved_days(saved_isos)
    if verified_days != len(saved_isos):
        LOGGER.warning("入库复核只有 %s/%s 天在表内可见", verified_days, len(saved_isos))

    if empty_days and not args.no_repair:
        conn = connect()
        try:
            recorded = record_unavailable_dates(
                conn,
                (("DCE", MARKET_UNAVAILABLE_SYMBOL, date.fromisoformat(iso)) for iso in empty_days),
                "dce_dayquotes_no_contract_rows",
            )
        finally:
            conn.close()
        LOGGER.info("源端确无合约行的交易日已记录 %s 条", recorded)

    remaining = remaining_dates(args.work_file, args.payload_dir, args.ingested_dir)
    report = {
        "script": "audit_futures_daily_dce_browser",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "command": "ingest",
        "days_ingested": written_days,
        "days_written_source": len(saved_isos),
        "days_verified_in_table": verified_days,
        "rows_written": written_rows,
        "source_empty_days": len(empty_days),
        "source_empty_sample": empty_days[:20],
        "deferred_empty_days": len(deferred_days),
        "deferred_sample": deferred_days[:20],
        "remaining_work_days": len(remaining),
        "remaining_sample": remaining[:20],
    }
    path = write_report(report, args.report_dir, "audit_futures_daily_dce_browser")
    LOGGER.info(
        "DCE 入库完成: days=%s rows=%s 源端空日=%s 待重试=%s 仍需=%s report=%s",
        written_days,
        written_rows,
        len(empty_days),
        len(deferred_days),
        len(remaining),
        path,
    )
    return 0 if not remaining else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch 大商所 daily history through a browser page that passes the WAF."
    )
    add_common_arguments(parser)
    parser.add_argument(
        "command",
        choices=["plan", "serve", "snippet", "status", "ingest"],
        help="plan=写工作清单 serve=起桥接服务 snippet=打印页内脚本 ingest=报文入库",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--work-file", type=Path, default=BRIDGE_DIR / "work.json")
    parser.add_argument("--payload-dir", type=Path, default=BRIDGE_DIR / "payloads")
    parser.add_argument("--ingested-dir", type=Path, default=BRIDGE_DIR / "ingested")
    parser.add_argument("--batch", type=int, default=120, help="days per database write")
    return parser


COMMANDS = {
    "plan": command_plan,
    "serve": command_serve,
    "snippet": command_snippet,
    "status": command_status,
    "ingest": command_ingest,
}


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
