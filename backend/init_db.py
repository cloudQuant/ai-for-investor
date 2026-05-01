#!/usr/bin/env python3
import asyncio

from sqlalchemy import text
from app.db.mysql import engine, Base
from app.models import *


async def create_tables():
    print("Creating database tables...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("Tables created successfully!")

    tables = [
        "users", "roles", "user_roles",
        "categories", "tags", "tag_relations", "blog_posts",
        "forum_categories", "forum_threads", "forum_replies", "forum_reports",
        "tools", "tool_manifests", "tool_jobs",
        "open_source_projects", "project_snapshots", "project_scores", "weekly_report_candidates", "discovery_keywords",
        "audit_logs", "user_preferences"
    ]

    async with engine.begin() as conn:
        for table in tables:
            try:
                result = await conn.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
                count = result.scalar()
                print(f"  - {table}: {count} rows")
            except Exception as e:
                print(f"  - {table}: created")

    print("\nDatabase initialization complete!")


if __name__ == "__main__":
    asyncio.run(create_tables())
