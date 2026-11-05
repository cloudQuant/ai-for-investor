"""Every collection script's standalone entry point has to name a member its class has.

831 of the 1057 scripts under `app/data_fetch/scripts` ended with `script = SomeScript();
script.run()` while neither the script class nor `AkshareToMySql`/`BinanceToMySql` defined `run`;
the scheduler hid it because it resolves `fetch_data` itself, so the files only crashed when run
directly. This census is what keeps the shape from coming back while the mypy plane is still
advisory, and it fails on its own blind spots: an unresolvable base class is a finding, not a skip.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

SCRIPT_ROOT: Final = Path(__file__).resolve().parents[1] / "app" / "data_fetch" / "scripts"

#: The two names the script driver treats as entry points. The census is limited to them
#: because the bases outside a script's own module define *neither* - `AkshareToMySql` and
#: `BinanceToMySql` offer `fetch_ak_data` / `save_to_mysql` / `create_table_if_not_exists`,
#: but no `run` and no `fetch_data` (their `FuncThread.run` is a thread override in a helper
#: class). Outside this vocabulary the census would have to model every provider method.
ENTRY_POINTS: Final = frozenset({"run", "fetch_data"})

#: Bases outside the script's own module, and the entry points each of them is known to define.
EXTERNAL_BASE_MEMBERS: Final = {
    "AkshareToMySql": frozenset(),
    "BinanceToMySql": frozenset(),
}

BROKEN_SAMPLE: Final = (
    "from app.data_fetch.providers.akshare_to_mysql import AkshareToMySql\n"
    "class Demo(AkshareToMySql):\n"
    "    def fetch_data(self, **kwargs):\n"
    "        return None\n"
    "def main():\n"
    "    script = Demo()\n"
    "    script.run()\n"
)

#: The two handles `Database` owns, and the reason they are nullable: `connect_db` establishes
#: them, `disconnect_db` drops them. Reading them as an attribute and calling into it is a union
#: dereference - that shape alone was 90 of the plane's mypy `union-attr` errors. The accessor
#: path is `require_cursor()` / `require_connection()`, which raise instead of handing back `None`.
DB_HANDLES: Final = frozenset({"cursor", "connection"})

DB_HANDLE_SAMPLE: Final = (
    "class Demo:\n"
    "    def go(self):\n"
    "        self.cursor.execute('SELECT 1')\n"
    "        self.connection.commit()\n"
    "        if self.connection:\n"
    "            self.connection.rollback()\n"
)


def _defines(node: ast.ClassDef, name: str) -> bool:
    return any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name
        for child in node.body
    )


def _has_member(
    cls: ast.ClassDef, pool: dict[str, ast.ClassDef], name: str, seen: set[str]
) -> bool | None:
    """`True`/`False` when this module decides it, `None` when a base is unknown to the census."""
    if cls.name in seen:
        return False
    seen.add(cls.name)
    if _defines(cls, name):
        return True
    for base in cls.bases:
        base_name = ast.unparse(base)
        if base_name in pool:
            if _has_member(pool[base_name], pool, name, seen) is True:
                return True
        elif base_name not in EXTERNAL_BASE_MEMBERS:
            return None
    return False


def _defects(source: str) -> tuple[int, int]:
    """Return (unresolvable-base count, calls naming a member the class does not have)."""
    tree = ast.parse(source)
    pool = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    unknown = 0
    broken = 0
    for func in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        bound: dict[str, str] = {}
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in pool
            ):
                bound[node.targets[0].id] = node.value.func.id
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ENTRY_POINTS
                and isinstance(node.func.value, ast.Name)
            ):
                cls_name = bound.get(node.func.value.id)
                if cls_name is None:
                    continue
                verdict = _has_member(pool[cls_name], pool, node.func.attr, set())
                if verdict is None:
                    unknown += 1
                elif verdict is False:
                    broken += 1
    return unknown, broken


def test_the_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _defects(BROKEN_SAMPLE) == (0, 1)


def test_no_collection_script_calls_an_entry_point_its_class_does_not_define() -> None:
    unknown_total = 0
    broken: list[str] = []
    files = 0
    for path in sorted(SCRIPT_ROOT.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        files += 1
        unknown, misses = _defects(path.read_text(encoding="utf-8"))
        unknown_total += unknown
        if misses:
            broken.append(f"{path.relative_to(SCRIPT_ROOT.parent.parent)} x{misses}")

    assert files == 1057, f"the census scope moved: {files} scripts"
    assert unknown_total == 0, f"{unknown_total} calls whose base class the census cannot resolve"
    assert not broken, f"scripts calling a member they do not have: {broken[:10]}"


def _db_handle_member_accesses(source: str) -> list[str]:
    """Every `self.<handle>.<member>` read in `source`.

    A bare `if self.connection:` is not a member access on the handle, so the legal
    "is the connection still up?" guards stay legal while the dereferences do not.
    """
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "self"
            and node.value.attr in DB_HANDLES
        ):
            hits.append(f"self.{node.value.attr}.{node.attr}")
    return hits


def test_the_handle_census_finds_the_dereferences_and_lets_the_guard_pass() -> None:
    assert _db_handle_member_accesses(DB_HANDLE_SAMPLE) == [
        "self.cursor.execute",
        "self.connection.commit",
        "self.connection.rollback",
    ]


def test_no_collection_script_dereferences_a_nullable_database_handle() -> None:
    offenders: list[str] = []
    files = 0
    for path in sorted(SCRIPT_ROOT.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        files += 1
        hits = _db_handle_member_accesses(path.read_text(encoding="utf-8"))
        if hits:
            offenders.append(f"{path.relative_to(SCRIPT_ROOT.parent.parent)}: {hits[:3]}")

    assert files == 1057, f"the census scope moved: {files} scripts"
    assert not offenders, f"scripts dereferencing the nullable handle: {offenders[:10]}"
