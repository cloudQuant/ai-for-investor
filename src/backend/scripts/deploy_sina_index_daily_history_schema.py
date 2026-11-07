"""Plan or hash-guard deployment of the separate Sina index-history table."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_fetch.providers.sina_index_history_schema import (  # noqa: E402
    BUSINESS_KEY,
    EXPECTED_COLUMNS,
    EXPECTED_INDEX_NAMES,
    TARGET_TABLE,
    ZERO_DEFAULT_COLUMNS,
    validate_predeployed_schema,
)

from app.data_fetch.configs.db_config import DB_CONFIG  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "reports" / "INDEX_SINA_DAILY_HISTORY.schema.sql"


class SchemaMismatchError(RuntimeError):
    """An existing table does not match the reviewed isolated contract."""


def _create_statement() -> str:
    """Load exactly one fixed CREATE statement from the review-owned schema file."""
    try:
        raw = SCHEMA_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaMismatchError("fixed Sina index schema file is unavailable") from exc
    executable_lines = [line for line in raw.splitlines() if not line.lstrip().startswith("--")]
    statement = "\n".join(executable_lines).strip()
    quote: str | None = None
    terminators: list[int] = []
    index = 0
    while index < len(statement):
        char = statement[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                if index + 1 < len(statement) and statement[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char == ";":
            terminators.append(index)
        index += 1
    if (
        not statement.upper().startswith(f"CREATE TABLE `{TARGET_TABLE}`".upper())
        or quote is not None
        or len(terminators) != 1
        or statement[terminators[0] + 1 :].strip()
    ):
        raise SchemaMismatchError("fixed Sina schema file must contain one CREATE TABLE only")
    column_pattern = re.compile(
        r"(?m)^\s*`(?P<name>[^`]+)`\s+"
        r"(?P<type>[A-Za-z]+(?:\(\d+(?:\s*,\s*\d+)?\))?(?:\s+UNSIGNED)?)\s+"
        r"(?P<nullability>NOT NULL|NULL)\b",
        re.IGNORECASE,
    )
    columns = {
        match.group("name").upper(): (
            re.sub(
                r"\s*([(),])\s*",
                r"\1",
                " ".join(match.group("type").casefold().split()),
            ),
            match.group("nullability").casefold(),
        )
        for match in column_pattern.finditer(statement)
    }
    if columns != {name: (type_name, "not null") for name, type_name in EXPECTED_COLUMNS.items()}:
        raise SchemaMismatchError("fixed Sina schema DDL columns differ from the write contract")
    index_names = {
        name.upper()
        for name in re.findall(
            r"(?:UNIQUE\s+)?KEY\s+`([^`]+)`|PRIMARY\s+KEY", statement, re.IGNORECASE
        )
        if name
    }
    # PRIMARY KEY has no quoted name in the SQL declaration and is checked separately.
    index_names.discard("")
    if (
        "PRIMARY KEY (`R_ID`)" not in statement.upper()
        or index_names | {"PRIMARY"} != EXPECTED_INDEX_NAMES
        or not re.search(r"ENGINE\s*=\s*INNODB\b", statement, re.IGNORECASE)
    ):
        raise SchemaMismatchError("fixed Sina schema DDL indexes or engine differ from contract")
    if any(
        f"`{name}`" in statement
        and re.search(rf"`{name}`\s+[^,\n]+\bDEFAULT\s+0\b", statement, re.IGNORECASE) is None
        for name in ZERO_DEFAULT_COLUMNS
    ):
        raise SchemaMismatchError("fixed Sina schema DDL flag defaults differ from contract")
    if not re.search(
        r"`CREATED_AT`\s+DATETIME\(6\)\s+NOT\s+NULL\s+DEFAULT\s+CURRENT_TIMESTAMP\(6\)",
        statement,
        re.IGNORECASE,
    ) or not re.search(
        r"`UPDATED_AT`\s+DATETIME\(6\)\s+NOT\s+NULL\s+DEFAULT\s+CURRENT_TIMESTAMP\(6\)\s+ON\s+UPDATE\s+CURRENT_TIMESTAMP\(6\)",
        statement,
        re.IGNORECASE,
    ):
        raise SchemaMismatchError("fixed Sina schema DDL timestamp defaults differ from contract")
    return statement


def _table_exists(cursor: Any) -> bool:
    cursor.execute(f"SHOW TABLES LIKE '{TARGET_TABLE}'")
    return bool(cursor.fetchall())


def inspect_plan(cursor: Any, *, schema_name: str) -> dict[str, Any]:
    """Return a create-only plan or verify an exact existing schema read-only."""
    statements = [_create_statement()] if not _table_exists(cursor) else []
    if not statements:
        try:
            validate_predeployed_schema(cursor, schema_name=schema_name)
        except RuntimeError as exc:
            raise SchemaMismatchError(str(exc)) from exc
    digest = hashlib.sha256(
        json.dumps(
            [TARGET_TABLE, statements, list(BUSINESS_KEY)],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "table": TARGET_TABLE,
        "statements": statements,
        "sha256": digest,
        "business_key": list(BUSINESS_KEY),
        "engine": "InnoDB",
        "source": "sina",
        "source_identity_requirement": "exact KLC_KL_<symbol> response assignment",
        "source_units_verified": False,
        "adjustment_basis_verified": False,
        "source_history_complete": False,
        "source_inception_verified": False,
        "calendar_verified": False,
        "legacy_table_preserved": "STOCK_ZH_INDEX_DAILY",
    }


def _require_reviewed_plan_hash(expected_sha256: str | None, actual_sha256: str) -> None:
    if expected_sha256 != actual_sha256:
        raise RuntimeError(
            "Reviewed Sina schema plan hash missing or changed; inspect a fresh plan"
        )


def main(argv: list[str] | None = None) -> int:
    """Print a metadata-only plan by default; apply requires the exact reviewed SHA."""
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
            result = inspect_plan(cursor, schema_name=str(DB_CONFIG["database"]))
            result["mode"] = "apply" if args.apply else "plan"
            result["verified"] = False
            if args.apply:
                _require_reviewed_plan_hash(args.expected_sha256, result["sha256"])
                for statement in result["statements"]:
                    cursor.execute(statement)
                connection.commit()
                if inspect_plan(cursor, schema_name=str(DB_CONFIG["database"]))["statements"]:
                    raise RuntimeError("Sina schema deployment did not satisfy its contract")
                result["verified"] = True
        finally:
            cursor.close()
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
