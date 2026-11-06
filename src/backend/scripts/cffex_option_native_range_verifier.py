"""Portable, independent CSV-to-warehouse verifier for CFFEX date ranges.

This module intentionally does not import the producer's source parser or any
report-tree helper. It reads the captured ZIP's literal CSV headers and maps
them to the deployed storage contract independently.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any

SOURCE = "cffex_monthly_archive"
MARKET = "CFFEX"
TIME_ZONE = "Asia/Shanghai"
URL_TEMPLATE = "http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 64
MAX_ROWS_PER_MEMBER = 20_000

STANDARD_HEADERS = (
    "合约代码",
    "今开盘",
    "最高价",
    "最低价",
    "成交量",
    "成交金额",
    "持仓量",
    "持仓变化",
    "今收盘",
    "今结算",
    "前结算",
    "涨跌1",
    "涨跌2",
    "Delta",
)
LEGACY_HEADERS_WITH_IV = (
    *STANDARD_HEADERS[:-1],
    "隐含波动率(%)",
    "Delta",
)
NATIVE_FIELD_MAP = {
    "今开盘": "OPEN_PRICE",
    "最高价": "HIGH_PRICE",
    "最低价": "LOW_PRICE",
    "今收盘": "CLOSE_PRICE",
    "今结算": "SETTLEMENT_PRICE",
    "前结算": "PREVIOUS_SETTLEMENT_PRICE",
    "涨跌1": "CHANGE_1",
    "涨跌2": "CHANGE_2",
    "成交量": "VOLUME",
    "成交金额": "AMOUNT_SOURCE_VALUE",
    "持仓量": "OPEN_INTEREST",
    "持仓变化": "OPEN_INTEREST_CHANGE",
    "Delta": "SOURCE_DELTA",
}
COMPARE_FIELDS = (
    "SOURCE",
    "MARKET",
    "OPTION_PRODUCT",
    "SOURCE_SYMBOL",
    "CONTRACT_MONTH",
    "OPTION_SIDE",
    "STRIKE_PRICE",
    "TRADE_DATE",
    "OPEN_PRICE",
    "HIGH_PRICE",
    "LOW_PRICE",
    "CLOSE_PRICE",
    "SETTLEMENT_PRICE",
    "PREVIOUS_SETTLEMENT_PRICE",
    "CHANGE_1",
    "CHANGE_2",
    "VOLUME",
    "AMOUNT_SOURCE_VALUE",
    "AMOUNT_UNIT",
    "OPEN_INTEREST",
    "OPEN_INTEREST_CHANGE",
    "SOURCE_DELTA",
    "SOURCE_DELTA_RAW",
    "SOURCE_ROW_JSON",
    "SOURCE_ROW_SHA256",
    "SOURCE_URL",
    "SOURCE_ARCHIVE_MONTH",
    "SOURCE_ARCHIVE_SHA256",
    "SOURCE_ARCHIVE_MEMBER_COUNT",
    "SOURCE_MEMBER_NAME",
    "SOURCE_MEMBER_SHA256",
    "SOURCE_MEMBER_OPTION_ROW_COUNT",
    "OBSERVED_AT_TIME_ZONE",
    "SOURCE_SCOPE",
    "SOURCE_SEQUENCE_COMPLETE",
    "SOURCE_COMPLETE",
    "QUALITY_STATUS",
)

_MEMBER_RE = re.compile(r"^(\d{8})_(\d+)\.csv$", re.IGNORECASE)
_OPTION_RE = re.compile(r"^(IO|HO|MO)(\d{4})-([CP])-(\d+(?:\.\d+)?)$")
_FUTURES_RE = re.compile(r"^(?:IF|IH|IC|IM|T|TF|TL|TS)\d{4}$")
_NULL = {"", "null", "--"}


def _parse_decimal(
    token: str,
    field: str,
    *,
    nullable: bool = False,
    nonnegative: bool = False,
) -> Decimal | None:
    text = str(token).strip()
    if text.casefold() in _NULL:
        if nullable:
            return None
        raise ValueError(f"required numeric field {field} is blank")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric field {field}: {token!r}") from exc
    if not number.is_finite():
        raise ValueError(f"non-finite numeric field {field}")
    if nonnegative and number < 0:
        raise ValueError(f"negative source field {field}")
    return number


def _parse_integer(token: str, field: str, *, nonnegative: bool) -> int:
    number = _parse_decimal(token, field)
    assert number is not None
    if number != number.to_integral_value():
        raise ValueError(f"non-integer source field {field}")
    value = int(number)
    if nonnegative and value < 0:
        raise ValueError(f"negative source field {field}")
    return value


def _parse_numeric_fields(raw: Mapping[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    volume = _parse_integer(raw.get("成交量", ""), "成交量", nonnegative=True)
    ohlc = [str(raw.get(header, "")).strip() for header in ("今开盘", "最高价", "最低价")]
    all_blank = all(value == "" for value in ohlc)
    all_null = all(value.casefold() == "null" for value in ohlc)
    no_trade_ohlc = (all_blank or all_null) and volume == 0

    for header, field in NATIVE_FIELD_MAP.items():
        token = str(raw.get(header, ""))
        if field == "VOLUME":
            values[field] = volume
        elif field == "OPEN_INTEREST":
            values[field] = _parse_integer(token, header, nonnegative=True)
        elif field == "OPEN_INTEREST_CHANGE":
            values[field] = _parse_integer(token, header, nonnegative=False)
        elif field == "SOURCE_DELTA":
            values[field] = _parse_decimal(token, header, nullable=True)
        elif field in {"OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE"}:
            values[field] = _parse_decimal(
                token,
                header,
                nullable=no_trade_ohlc,
                nonnegative=True,
            )
        else:
            values[field] = _parse_decimal(
                token,
                header,
                nonnegative=field
                in {
                    "OPEN_PRICE",
                    "HIGH_PRICE",
                    "LOW_PRICE",
                    "CLOSE_PRICE",
                    "SETTLEMENT_PRICE",
                    "PREVIOUS_SETTLEMENT_PRICE",
                    "AMOUNT_SOURCE_VALUE",
                },
            )

    any_blank_or_null = any(value == "" or value.casefold() == "null" for value in ohlc)
    if no_trade_ohlc:
        for field in ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE"):
            if values[field] is not None:
                raise ValueError("empty no-trade OHLC was parsed as a numeric value")
    elif any_blank_or_null:
        raise ValueError("null OHLC requires all three fields to share one empty representation")
    elif (
        values["HIGH_PRICE"] < values["LOW_PRICE"]
        or values["HIGH_PRICE"]
        < max(values["OPEN_PRICE"], values["CLOSE_PRICE"], values["LOW_PRICE"])
        or values["LOW_PRICE"]
        > min(values["OPEN_PRICE"], values["CLOSE_PRICE"], values["HIGH_PRICE"])
    ):
        raise ValueError("source OHLC relationship is invalid")
    return values


def _canonical_raw(raw_row: Mapping[Any, Any]) -> dict[str, str]:
    if None in raw_row:
        raise ValueError("CSV row contains extra cells")
    return {str(key).strip().lstrip("\ufeff"): str(value or "") for key, value in raw_row.items()}


def _validate_member_name(name: str, month: str) -> tuple[str, date]:
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or name.startswith("/")
        or PurePosixPath(name).is_absolute()
        or any(part in {".", ".."} for part in PurePosixPath(name).parts)
        or len(PurePosixPath(name).parts) != 1
    ):
        raise ValueError(f"unsafe ZIP member path: {name!r}")
    match = _MEMBER_RE.fullmatch(name)
    if match is None:
        raise ValueError(f"unexpected dated CSV member name: {name!r}")
    try:
        member_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid date in ZIP member name: {name!r}") from exc
    if member_date.strftime("%Y%m") != month:
        raise ValueError(f"member date escaped archive month: {name!r}")
    return name, member_date


def parse_native_range(
    archive_body: bytes, *, month: str, start: date, end: date
) -> dict[str, Any]:
    """Parse native CSV rows in one exact range without using producer code."""
    if not re.fullmatch(r"\d{6}", month) or start > end:
        raise ValueError("invalid month or date range")
    if start.strftime("%Y%m") != month or end.strftime("%Y%m") != month:
        raise ValueError("range must stay within the requested archive month")
    if len(archive_body) > MAX_ARCHIVE_BYTES:
        raise ValueError("captured ZIP exceeds verifier size bound")

    archive_sha = hashlib.sha256(archive_body).hexdigest()
    member_meta: dict[str, dict[str, Any]] = {}
    source_rows: dict[tuple[str, date], dict[str, Any]] = {}
    invalid_rows: list[dict[str, Any]] = []
    unknown_codes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    seen_names: set[str] = set()
    all_option_keys: set[tuple[str, date]] = set()

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_body))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("captured response is not a valid ZIP") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("captured ZIP exceeds member-count bound")
        if sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("captured ZIP exceeds uncompressed-size bound")
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"ZIP CRC validation failed: {bad_member!r}")

        eligible: list[tuple[str, date, bytes]] = []
        for info in infos:
            if info.is_dir():
                raise ValueError(f"unexpected ZIP directory: {info.filename!r}")
            if info.flag_bits & 0x1 or info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"unsupported or oversized ZIP member: {info.filename!r}")
            if info.compress_size == 0 and info.file_size:
                raise ValueError(f"invalid ZIP compression size: {info.filename!r}")
            if info.compress_size and info.file_size / info.compress_size > 200:
                raise ValueError(f"ZIP member compression ratio exceeds bound: {info.filename!r}")
            name, member_day = _validate_member_name(info.filename, month)
            if name in seen_names:
                raise ValueError(f"duplicate ZIP member: {name}")
            seen_names.add(name)
            data = archive.read(info)
            member_sha = hashlib.sha256(data).hexdigest()
            member_meta[name] = {
                "date": member_day.isoformat(),
                "sha256": member_sha,
                "bytes": len(data),
                "option_row_count": 0,
            }
            eligible.append((name, member_day, data))

        for name, member_day, data in eligible:
            try:
                text = data.decode("gb2312")
            except UnicodeDecodeError as exc:
                raise ValueError(f"member is not valid GB2312: {name}") from exc
            reader = csv.DictReader(io.StringIO(text, newline=""))
            if reader.fieldnames is None:
                raise ValueError(f"member has no header: {name}")
            headers = tuple(str(value).strip().lstrip("\ufeff") for value in reader.fieldnames)
            if headers not in (STANDARD_HEADERS, LEGACY_HEADERS_WITH_IV):
                raise ValueError(f"unreviewed CFFEX CSV header in {name}: {headers!r}")

            member_options = 0
            for row_number, record in enumerate(reader, start=2):
                if row_number > MAX_ROWS_PER_MEMBER + 1:
                    raise ValueError(f"member row count exceeds limit: {name}")
                try:
                    raw = _canonical_raw(record)
                except ValueError as exc:
                    invalid_rows.append(
                        {"member": name, "row_number": row_number, "error": str(exc)}
                    )
                    continue
                symbol = raw.get("合约代码", "").strip()
                if symbol in {"合计", "小计"}:
                    counts[f"summary:{symbol}"] += 1
                    continue
                if not symbol:
                    invalid_rows.append(
                        {"member": name, "row_number": row_number, "error": "blank contract code"}
                    )
                    continue
                option = _OPTION_RE.fullmatch(symbol)
                if option is None:
                    if _FUTURES_RE.fullmatch(symbol):
                        counts["non_option_cffex_futures"] += 1
                    else:
                        unknown_codes.append(
                            {"member": name, "row_number": row_number, "source_symbol": symbol}
                        )
                    continue
                member_options += 1
                if (symbol, member_day) in all_option_keys:
                    invalid_rows.append(
                        {
                            "member": name,
                            "row_number": row_number,
                            "key": [symbol, member_day.isoformat()],
                            "error": "duplicate exact option key",
                        }
                    )
                    continue
                all_option_keys.add((symbol, member_day))
                try:
                    numeric = _parse_numeric_fields(raw)
                    product, contract_month, side, strike_text = option.groups()
                    strike = _parse_decimal(strike_text, "contract strike")
                    if strike is None or strike <= 0:
                        raise ValueError("strike must be positive")
                except ValueError as exc:
                    invalid_rows.append(
                        {
                            "member": name,
                            "row_number": row_number,
                            "key": [symbol, member_day.isoformat()],
                            "error": str(exc),
                        }
                    )
                    continue
                if not start <= member_day <= end:
                    continue
                raw_json = json.dumps(
                    raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                row = {
                    "SOURCE": SOURCE,
                    "MARKET": MARKET,
                    "OPTION_PRODUCT": product,
                    "SOURCE_SYMBOL": symbol,
                    "CONTRACT_MONTH": contract_month,
                    "OPTION_SIDE": side,
                    "STRIKE_PRICE": strike,
                    "TRADE_DATE": member_day,
                    **numeric,
                    "AMOUNT_UNIT": "unknown",
                    "SOURCE_DELTA_RAW": raw.get("Delta", ""),
                    "SOURCE_ROW_JSON": raw_json,
                    "SOURCE_ROW_SHA256": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
                    "SOURCE_URL": URL_TEMPLATE.format(month=month),
                    "SOURCE_ARCHIVE_MONTH": month,
                    "SOURCE_ARCHIVE_SHA256": archive_sha,
                    "SOURCE_ARCHIVE_MEMBER_COUNT": len(member_meta),
                    "SOURCE_MEMBER_NAME": name,
                    "SOURCE_MEMBER_SHA256": member_meta[name]["sha256"],
                    "SOURCE_MEMBER_OPTION_ROW_COUNT": None,
                    "OBSERVED_AT_TIME_ZONE": TIME_ZONE,
                    "SOURCE_SCOPE": f"cffex:option-history:monthly-archive:{month}",
                    "SOURCE_SEQUENCE_COMPLETE": 1,
                    "SOURCE_COMPLETE": 0,
                    "QUALITY_STATUS": "partial",
                }
                source_rows[(symbol, member_day)] = row
            member_meta[name]["option_row_count"] = member_options

    if not member_meta:
        raise ValueError("archive contains no valid dated CSV members")
    for row in source_rows.values():
        row["SOURCE_MEMBER_OPTION_ROW_COUNT"] = member_meta[row["SOURCE_MEMBER_NAME"]][
            "option_row_count"
        ]

    in_range_invalid = [
        item
        for item in invalid_rows
        if start <= date.fromisoformat(member_meta[item["member"]]["date"]) <= end
    ]
    in_range_unknown = [
        item
        for item in unknown_codes
        if start <= date.fromisoformat(member_meta[item["member"]]["date"]) <= end
    ]
    return {
        "source_rows": source_rows,
        "source_key_count": len(source_rows),
        "archive_sha256": archive_sha,
        "archive_bytes": len(archive_body),
        "member_count": len(member_meta),
        "members": member_meta,
        "invalid_rows": invalid_rows,
        "in_range_invalid_rows": in_range_invalid,
        "unknown_contract_codes": unknown_codes,
        "in_range_unknown_contract_codes": in_range_unknown,
        "source_counts": dict(sorted(counts.items())),
        "requested_date_range": [start.isoformat(), end.isoformat()],
        "monthly_archive_fully_valid": not invalid_rows and not unknown_codes,
        "source_sequence_completeness": "archive member enumeration only; no exchange-calendar claim",
    }


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _equal(field: str, expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, Decimal):
        try:
            value = Decimal(str(actual))
        except (InvalidOperation, ValueError, TypeError):
            return False
        return value.is_finite() and value == expected
    if isinstance(expected, int):
        try:
            number = Decimal(str(actual))
        except (InvalidOperation, ValueError, TypeError):
            return False
        return number.is_finite() and number == expected
    if field == "TRADE_DATE":
        try:
            return _date(actual) == expected
        except (TypeError, ValueError):
            return False
    if field == "SOURCE_ROW_JSON":
        try:
            return json.loads(str(actual)) == json.loads(str(expected))
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
    return str(expected) == str(actual)


def compare_native_range(
    archive_body: bytes,
    sql_rows: Sequence[Mapping[str, Any]],
    *,
    month: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Compare an independently parsed native date range to fresh SQL rows."""
    parsed = parse_native_range(archive_body, month=month, start=start, end=end)
    source_rows: dict[tuple[str, date], dict[str, Any]] = parsed["source_rows"]
    sql_by_key: dict[tuple[str, date], Mapping[str, Any]] = {}
    duplicate_sql_keys: list[list[str]] = []
    scope_escaped_rows = 0
    for row in sql_rows:
        try:
            key = (str(row.get("SOURCE_SYMBOL")), _date(row.get("TRADE_DATE")))
        except (TypeError, ValueError):
            duplicate_sql_keys.append([str(row.get("SOURCE_SYMBOL")), "invalid-date"])
            continue
        if row.get("SOURCE") != SOURCE or row.get("SOURCE_ARCHIVE_MONTH") != month:
            scope_escaped_rows += 1
        if not start <= key[1] <= end:
            scope_escaped_rows += 1
        if key in sql_by_key:
            duplicate_sql_keys.append([key[0], key[1].isoformat()])
        sql_by_key[key] = row

    source_keys, sql_keys = set(source_rows), set(sql_by_key)
    missing = sorted(source_keys - sql_keys, key=lambda key: (key[1], key[0]))
    extras = sorted(sql_keys - source_keys, key=lambda key: (key[1], key[0]))
    mismatches: list[dict[str, Any]] = []
    compared = 0
    for key in sorted(source_keys & sql_keys, key=lambda item: (item[1], item[0])):
        expected_row, actual_row = source_rows[key], sql_by_key[key]
        for field in COMPARE_FIELDS:
            compared += 1
            if not _equal(field, expected_row[field], actual_row.get(field)):
                if len(mismatches) < 100:
                    mismatches.append(
                        {
                            "key": [key[0], key[1].isoformat()],
                            "field": field,
                            "expected": str(expected_row[field]),
                            "actual": str(actual_row.get(field)),
                        }
                    )

    exact_positive_keys = bool(source_keys) and bool(sql_keys)
    matched = (
        exact_positive_keys
        and len(source_keys) == len(sql_keys)
        and not missing
        and not extras
        and not duplicate_sql_keys
        and scope_escaped_rows == 0
        and not mismatches
        and not parsed["in_range_invalid_rows"]
        and not parsed["in_range_unknown_contract_codes"]
        and compared == len(source_keys) * len(COMPARE_FIELDS)
    )
    return {
        "matched": matched,
        "status": "matched" if matched else "failed_closed",
        "month": month,
        "requested_date_range": parsed["requested_date_range"],
        "archive_sha256": parsed["archive_sha256"],
        "archive_bytes": parsed["archive_bytes"],
        "member_count": parsed["member_count"],
        "members": parsed["members"],
        "source_key_count": len(source_keys),
        "sql_key_count": len(sql_keys),
        "compared_field_count": len(COMPARE_FIELDS),
        "field_comparisons": compared,
        "compared_fields": list(COMPARE_FIELDS),
        "missing_in_sql": [[key[0], key[1].isoformat()] for key in missing[:100]],
        "sql_only": [[key[0], key[1].isoformat()] for key in extras[:100]],
        "duplicate_sql_keys": duplicate_sql_keys[:100],
        "scope_escaped_sql_row_count": scope_escaped_rows,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "in_range_invalid_rows": parsed["in_range_invalid_rows"][:100],
        "in_range_unknown_contract_codes": parsed["in_range_unknown_contract_codes"][:100],
        "monthly_archive_fully_valid": parsed["monthly_archive_fully_valid"],
        "source_complete": False,
        "month_verified": False,
        "source_sequence_completeness": parsed["source_sequence_completeness"],
        "source_fields_independent_of_producer_parser": True,
    }
