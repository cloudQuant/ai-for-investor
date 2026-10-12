"""Explicit one-shot administrator bootstrap after schema migrations."""

import asyncio

from app.db.database import create_default_admin, verify_database_schema


async def bootstrap_admin() -> None:
    """Verify the migrated schema, then create the configured administrator."""
    await verify_database_schema()
    await create_default_admin()


def main() -> None:
    asyncio.run(bootstrap_admin())


if __name__ == "__main__":
    main()
