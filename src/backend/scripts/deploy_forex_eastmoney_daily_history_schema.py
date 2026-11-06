"""Plan or hash-guard deployment of canonical Eastmoney FX daily history."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_fetch.configs.db_config import DB_CONFIG  # noqa: E402

TABLE_NAME = "FOREX_EASTMONEY_DAILY_HISTORY"
UNIQUE_COLUMNS = ["SOURCE", "SOURCE_MARKET_CODE", "SOURCE_SYMBOL", "TRADE_DATE"]
LOOKUP_COLUMNS = ["SOURCE_SYMBOL", "TRADE_DATE"]
PRIMARY_COLUMNS = ["R_ID"]
CREATE_TABLE_SQL = """CREATE TABLE `FOREX_EASTMONEY_DAILY_HISTORY` (
  `R_ID` CHAR(32) NOT NULL,
  `SOURCE` VARCHAR(32) NOT NULL,
  `SOURCE_MARKET_CODE` VARCHAR(3) NOT NULL,
  `SOURCE_SYMBOL` VARCHAR(16) NOT NULL,
  `SOURCE_NAME` VARCHAR(100) NOT NULL,
  `TRADE_DATE` DATE NOT NULL,
  `OPEN` DECIMAL(24,10) NOT NULL,
  `CLOSE` DECIMAL(24,10) NOT NULL,
  `HIGH` DECIMAL(24,10) NOT NULL,
  `LOW` DECIMAL(24,10) NOT NULL,
  `PRICE_ADJUSTMENT_BASIS` VARCHAR(32) NOT NULL,
  `SOURCE_FQT_PARAMETER` VARCHAR(8) NOT NULL,
  `REQUEST_START_DATE` DATE NOT NULL,
  `REQUEST_END_DATE` DATE NOT NULL,
  `SOURCE_OBSERVED_AT_UTC` DATETIME(6) NOT NULL,
  `SOURCE_URL` VARCHAR(512) NOT NULL,
  `SOURCE_HTTP_STATUS` SMALLINT UNSIGNED NOT NULL,
  `SOURCE_RESPONSE_BYTES` BIGINT UNSIGNED NOT NULL,
  `SOURCE_RESPONSE_ROW_COUNT` INT UNSIGNED NOT NULL,
  `SOURCE_RESPONSE_SHA256` CHAR(64) NOT NULL,
  `SOURCE_ROW_JSON` JSON NOT NULL,
  `SOURCE_ROW_SHA256` CHAR(64) NOT NULL,
  PRIMARY KEY (`R_ID`),
  UNIQUE KEY `uq_eastmoney_fx_day_source` (`SOURCE`, `SOURCE_MARKET_CODE`, `SOURCE_SYMBOL`, `TRADE_DATE`),
  KEY `idx_eastmoney_fx_pair_day` (`SOURCE_SYMBOL`, `TRADE_DATE`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='Eastmoney FX daily source rows; SAFE, CFETS, units, fqt semantics, calendar and inception stay separate/unverified'"""

EXPECTED_COLUMNS: dict[str, tuple[str, bool, Any]] = {
    "r_id": ("char(32)", False, None),
    "source": ("varchar(32)", False, None),
    "source_market_code": ("varchar(3)", False, None),
    "source_symbol": ("varchar(16)", False, None),
    "source_name": ("varchar(100)", False, None),
    "trade_date": ("date", False, None),
    "open": ("decimal(24,10)", False, None),
    "close": ("decimal(24,10)", False, None),
    "high": ("decimal(24,10)", False, None),
    "low": ("decimal(24,10)", False, None),
    "price_adjustment_basis": ("varchar(32)", False, None),
    "source_fqt_parameter": ("varchar(8)", False, None),
    "request_start_date": ("date", False, None),
    "request_end_date": ("date", False, None),
    "source_observed_at_utc": ("datetime(6)", False, None),
    "source_url": ("varchar(512)", False, None),
    "source_http_status": ("smallint unsigned", False, None),
    "source_response_bytes": ("bigint unsigned", False, None),
    "source_response_row_count": ("int unsigned", False, None),
    "source_response_sha256": ("char(64)", False, None),
    "source_row_json": ("json", False, None),
    "source_row_sha256": ("char(64)", False, None),
}

_TABLE_ENGINE_SQL = (
    "SELECT ENGINE FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
)


class SchemaMismatchError(RuntimeError):
    """An existing FX history target does not match the reviewed contract."""


def _value(row: Any, field: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(field)
    if isinstance(row, (tuple, list)) and len(row) > index:
        return row[index]
    return None


def _table_engine(cursor: Any) -> str | None:
    cursor.execute(_TABLE_ENGINE_SQL, (TABLE_NAME,))
    rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise SchemaMismatchError("schema_mismatch: target table lookup was ambiguous")
    engine = _value(rows[0], "ENGINE", 0)
    if not isinstance(engine, str) or not engine.strip():
        raise SchemaMismatchError("schema_mismatch: target table engine is unknown")
    if engine.casefold() != "innodb":
        raise SchemaMismatchError(
            f"schema_mismatch: target table engine must be InnoDB, found {engine}"
        )
    return engine


def _normalize_default(value: Any) -> Any:
    if value is None or str(value).strip().casefold() == "null":
        return None
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _index_matches(rows: list[Any], *, columns: list[str], unique: bool) -> bool:
    try:
        ordered = sorted(rows, key=lambda row: int(_value(row, "Seq_in_index", 3)))
        actual_columns = [str(_value(row, "Column_name", 4)).upper() for row in ordered]
        non_unique = {int(_value(row, "Non_unique", 1)) for row in ordered}
    except (TypeError, ValueError):
        return False
    return (
        actual_columns == columns
        and non_unique == ({0} if unique else {1})
        and all(_value(row, "Sub_part", 7) is None for row in ordered)
    )


def inspect_plan(cursor: Any) -> dict[str, Any]:
    """Return create-only DDL for an absent target or verify its exact contract."""
    engine = _table_engine(cursor)
    if engine is None:
        statements = [CREATE_TABLE_SQL]
    else:
        cursor.execute(f"SHOW COLUMNS FROM `{TABLE_NAME}`")
        columns = {str(_value(row, "Field", 0)).casefold(): row for row in cursor.fetchall()}
        missing = sorted(set(EXPECTED_COLUMNS) - set(columns))
        extra = sorted(set(columns) - set(EXPECTED_COLUMNS))
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing columns: {', '.join(missing)}")
            if extra:
                details.append(f"unexpected columns: {', '.join(extra)}")
            raise SchemaMismatchError("schema_mismatch: " + "; ".join(details))
        for name, (expected_type, expected_nullable, expected_default) in EXPECTED_COLUMNS.items():
            row = columns[name]
            actual_type = str(_value(row, "Type", 1) or "").casefold()
            actual_nullable = str(_value(row, "Null", 2) or "").casefold() == "yes"
            actual_default = _normalize_default(_value(row, "Default", 4))
            if (
                actual_type != expected_type
                or actual_nullable is not expected_nullable
                or actual_default != expected_default
            ):
                raise SchemaMismatchError(
                    f"schema_mismatch: `{name}` expected {expected_type} "
                    f"{'NULL' if expected_nullable else 'NOT NULL'} default={expected_default!r}, "
                    f"found {actual_type} {'NULL' if actual_nullable else 'NOT NULL'} "
                    f"default={actual_default!r}"
                )

        cursor.execute(f"SHOW INDEX FROM `{TABLE_NAME}`")
        groups: dict[str, list[Any]] = {}
        for row in cursor.fetchall():
            key_name = _value(row, "Key_name", 2)
            if key_name is not None:
                groups.setdefault(str(key_name), []).append(row)
        if not any(
            _index_matches(rows, columns=UNIQUE_COLUMNS, unique=True) for rows in groups.values()
        ):
            raise SchemaMismatchError(
                f"schema_mismatch: requires unique key ({', '.join(UNIQUE_COLUMNS)})"
            )
        if not any(
            name.casefold() == "primary"
            and _index_matches(rows, columns=PRIMARY_COLUMNS, unique=True)
            for name, rows in groups.items()
        ):
            raise SchemaMismatchError(
                f"schema_mismatch: requires primary key ({', '.join(PRIMARY_COLUMNS)})"
            )
        if not any(
            _index_matches(rows, columns=LOOKUP_COLUMNS, unique=False) for rows in groups.values()
        ):
            raise SchemaMismatchError(
                f"schema_mismatch: requires lookup index ({', '.join(LOOKUP_COLUMNS)})"
            )
        statements = []

    digest = hashlib.sha256(
        json.dumps([TABLE_NAME, statements], sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "table": TABLE_NAME,
        "statements": statements,
        "sha256": digest,
        "engine": "InnoDB",
        "source": "eastmoney",
        "business_key": UNIQUE_COLUMNS,
        "business_date_column": "TRADE_DATE",
        "observation_time_column": "SOURCE_OBSERVED_AT_UTC (naive DATETIME(6), UTC by contract)",
        "price_adjustment_basis": "unknown (source request retains fqt=1)",
        "price_unit_verified": False,
        "source_complete": False,
        "source_pagination_verified": False,
        "lifecycle_verified": False,
        "calendar_verified": False,
        "safe_reference_separate": True,
        "cfets_spot_separate": True,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the read-only schema plan; apply only for an exact reviewed hash."""
    import mysql.connector

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    options = {**DB_CONFIG, "autocommit": not args.apply}
    with mysql.connector.connect(**options) as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            result = inspect_plan(cursor)
            result["mode"] = "apply" if args.apply else "plan"
            result["verified"] = False
            if args.apply:
                if args.expected_sha256 != result["sha256"]:
                    raise RuntimeError(
                        "Reviewed plan hash missing or changed; inspect a fresh plan"
                    )
                for statement in result["statements"]:
                    cursor.execute(statement)
                connection.commit()
                if inspect_plan(cursor)["statements"]:
                    raise RuntimeError("Schema deployment did not satisfy the reviewed contract")
                result["verified"] = True
        finally:
            cursor.close()

    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
