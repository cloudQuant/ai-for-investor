"""Tests for scripts/audit_futures_daily_dce_browser.py - the 大商所 browser leg.

The bridge exists because DCE's dayQuotes feed refuses non-browser clients, so the
audits can only mark DCE gaps as source-unavailable. These cover the parts that decide
what is owed and whether a payload really landed; no database, no network.
"""

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "src" / "backend" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import audit_futures_daily_dce_browser as bridge  # noqa: E402


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None
        self.params = None

    def execute(self, sql, params=None):
        self.executed = " ".join(sql.split())
        self.params = params

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_fallback_only_query_excludes_the_fallback_label_and_binds_both_params():
    today = date(2026, 3, 2)
    conn = FakeConn([(today,)])

    result = bridge.load_fallback_only_dates(conn, "DCE")

    assert result == {today}
    assert "HAVING SUM(DATA_SOURCE <> %s) = 0" in conn.cursor_obj.executed
    assert conn.cursor_obj.params == ("DCE", "新浪期货兜底")
    assert conn.cursor_obj.executed.count("%s") == len(conn.cursor_obj.params)


def test_build_work_covers_absent_days_and_fallback_only_days():
    expected = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    actual = {date(2026, 1, 5), date(2026, 1, 6)}

    work = bridge.build_work(
        expected,
        actual,
        fallback_only={date(2026, 1, 6)},
        unavailable=set(),
    )

    assert work == [date(2026, 1, 6), date(2026, 1, 7)]


def test_build_work_respects_the_unavailable_ledger():
    expected = [date(2001, 12, 31), date(2002, 1, 4)]

    assert bridge.build_work(expected, set(), set(), set(expected)) == []


def test_frame_for_day_maps_contracts_and_drops_subtotal_rows():
    rows = [
        {
            "variety": "豆一",
            "contractId": "a2611",
            "open": "5360",
            "high": "5414",
            "low": "5336",
            "close": "5404",
            "lastClear": "5394",
            "clearPrice": "5422",
            "volumn": 280336,
            "openInterest": 345488,
            "turnover": "1512000",
        },
        {"variety": "小计", "contractId": None},
        {"variety": "总计", "contractId": None},
    ]

    frame = bridge.frame_for_day("20261016", rows)

    assert len(frame) == 1
    record = frame.iloc[0]
    assert list(frame.columns) == bridge.COLUMNS
    assert record["symbol"] == "a2611"
    assert record["variety"] == "A"
    assert record["date"] == "2026-10-16"
    assert record["settle"] == "5422"
    assert record["pre_settle"] == "5394"
    assert record["volume"] == 280336
    assert record["open_interest"] == 345488


def test_frame_for_day_returns_typed_empty_frame_when_only_totals_are_listed():
    frame = bridge.frame_for_day("20011231", [{"variety": "总计", "contractId": None}])

    assert frame.empty
    assert list(frame.columns) == bridge.COLUMNS


def test_work_list_skips_dates_with_a_payload_in_either_directory(tmp_path):
    work = tmp_path / "work.json"
    payloads = tmp_path / "payloads"
    ingested = tmp_path / "ingested"
    payloads.mkdir()
    ingested.mkdir()
    work.write_text(
        json.dumps(["2026-01-05", "2026-01-06", "2026-01-07"]),
        encoding="utf8",
    )
    (payloads / "20260105.json").write_text("{}", encoding="utf8")
    (ingested / "20260106.json").write_text("{}", encoding="utf8")

    assert bridge.remaining_dates(work, payloads, ingested) == ["2026-01-07"]


def test_saved_stems_reads_every_directory_it_is_given(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "20260105.json").write_text("{}", encoding="utf8")
    (second / "20260106.json").write_text("{}", encoding="utf8")

    assert bridge.saved_stems(first, second) == {"20260105", "20260106"}


def test_post_path_only_accepts_eight_digit_dates():
    assert bridge.POST_PATH_RE.match("/dce/20261016").group(1) == "20261016"
    for rejected in ("/dce/2026-10-16", "/dce/../etc", "/work", "/dce/2026101.json"):
        assert bridge.POST_PATH_RE.match(rejected) is None


def test_verify_saved_days_counts_only_days_the_table_shows(monkeypatch):
    seen = {}

    class StubConn:
        def close(self):
            pass

    def fake_load(conn, market, start, end):
        seen.update({"market": market, "start": start, "end": end})
        return {date(2026, 1, 5), date(2026, 1, 7)}

    monkeypatch.setattr(bridge, "connect", StubConn)
    monkeypatch.setattr(bridge, "load_market_dates", fake_load)

    assert bridge.verify_saved_days(["2026-01-05", "2026-01-06", "2026-01-07"]) == 2
    assert seen == {"market": "DCE", "start": date(2026, 1, 5), "end": date(2026, 1, 7)}
    assert bridge.verify_saved_days([]) == 0


def test_page_snippet_points_at_the_loopback_sink_and_the_real_feed():
    snippet = bridge.PAGE_SNIPPET % {"api": bridge.DAY_QUOTES_URL, "port": 18900}

    assert "http://127.0.0.1:18900" in snippet
    assert bridge.DAY_QUOTES_URL in snippet
    assert "/dce/" in snippet
