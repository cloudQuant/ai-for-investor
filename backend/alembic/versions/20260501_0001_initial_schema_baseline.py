"""initial schema baseline

Revision ID: 20260501_0001
Revises: 
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260501_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_categories_slug"), "categories", ["slug"], unique=True)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tags_name"), "tags", ["name"], unique=True)
    op.create_index(op.f("ix_tags_slug"), "tags", ["slug"], unique=True)

    op.create_table(
        "forum_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("thread_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_forum_categories_slug"), "forum_categories", ["slug"], unique=True)

    op.create_table(
        "tool_manifests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("image", sa.String(length=500), nullable=True),
        sa.Column("entrypoint", sa.JSON(), nullable=True),
        sa.Column("parameters_schema", sa.JSON(), nullable=True),
        sa.Column("resources", sa.JSON(), nullable=True),
        sa.Column("network", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("security_review", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "discovery_keywords",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("keyword", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discovery_keywords_keyword"), "discovery_keywords", ["keyword"], unique=False)

    op.create_table(
        "open_source_projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("forks", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("license", sa.String(length=100), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("latest_commit_at", sa.DateTime(), nullable=True),
        sa.Column("latest_release_at", sa.DateTime(), nullable=True),
        sa.Column("readme_summary", sa.Text(), nullable=True),
        sa.Column("score_relevance", sa.Float(), nullable=True),
        sa.Column("score_activity", sa.Float(), nullable=True),
        sa.Column("score_influence", sa.Float(), nullable=True),
        sa.Column("score_reproducibility", sa.Float(), nullable=True),
        sa.Column("score_security", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("risk_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_open_source_projects_repo_full_name"), "open_source_projects", ["repo_full_name"], unique=True)
    op.create_index(op.f("ix_open_source_projects_status"), "open_source_projects", ["status"], unique=False)

    op.create_table(
        "blog_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_blog_posts_slug"), "blog_posts", ["slug"], unique=True)
    op.create_index(op.f("ix_blog_posts_status"), "blog_posts", ["status"], unique=False)

    op.create_table(
        "tag_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["blog_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "forum_threads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True),
        sa.Column("is_locked", sa.Boolean(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("reply_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("last_replied_at", sa.DateTime(), nullable=True),
        sa.Column("linked_post_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["forum_categories.id"]),
        sa.ForeignKeyConstraint(["linked_post_id"], ["blog_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_category_last_replied", "forum_threads", ["category_id", "last_replied_at"], unique=False)
    op.create_index(op.f("ix_forum_threads_is_featured"), "forum_threads", ["is_featured"], unique=False)
    op.create_index(op.f("ix_forum_threads_is_locked"), "forum_threads", ["is_locked"], unique=False)
    op.create_index(op.f("ix_forum_threads_is_pinned"), "forum_threads", ["is_pinned"], unique=False)
    op.create_index(op.f("ix_forum_threads_status"), "forum_threads", ["status"], unique=False)

    op.create_table(
        "tools",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("run_mode", sa.String(length=20), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("license", sa.String(length=50), nullable=True),
        sa.Column("resource_cost", sa.String(length=255), nullable=True),
        sa.Column("usage_limitations", sa.Text(), nullable=True),
        sa.Column("financial_risk_reminder", sa.Text(), nullable=True),
        sa.Column("execution_risk_reminder", sa.Text(), nullable=True),
        sa.Column("manifest_id", sa.Integer(), nullable=True),
        sa.Column("config_status", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["manifest_id"], ["tool_manifests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tools_config_status"), "tools", ["config_status"], unique=False)
    op.create_index(op.f("ix_tools_slug"), "tools", ["slug"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("assigned_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "forum_replies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["forum_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_thread_created", "forum_replies", ["thread_id", "created_at"], unique=False)
    op.create_index(op.f("ix_forum_replies_status"), "forum_replies", ["status"], unique=False)

    op.create_table(
        "forum_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("reply_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("handler_id", sa.Integer(), nullable=True),
        sa.Column("handler_note", sa.Text(), nullable=True),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["handler_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reply_id"], ["forum_replies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["forum_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_forum_reports_status"), "forum_reports", ["status"], unique=False)

    op.create_table(
        "tool_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=50), nullable=False),
        sa.Column("tool_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_created", "tool_jobs", ["user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_tool_jobs_job_id"), "tool_jobs", ["job_id"], unique=True)
    op.create_index(op.f("ix_tool_jobs_status"), "tool_jobs", ["status"], unique=False)

    op.create_table(
        "project_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("keyword_id", sa.Integer(), nullable=True),
        sa.Column("repo_full_name", sa.String(length=255), nullable=True),
        sa.Column("repo_url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("forks", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("license_signal", sa.String(length=100), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("readme_summary", sa.Text(), nullable=True),
        sa.Column("latest_commit_at", sa.DateTime(), nullable=True),
        sa.Column("latest_release_at", sa.DateTime(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("error_detail", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["keyword_id"], ["discovery_keywords.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["open_source_projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_snapshots_collected_at"), "project_snapshots", ["collected_at"], unique=False)
    op.create_index(op.f("ix_project_snapshots_keyword_id"), "project_snapshots", ["keyword_id"], unique=False)
    op.create_index(op.f("ix_project_snapshots_project_id"), "project_snapshots", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_snapshots_repo_full_name"), "project_snapshots", ["repo_full_name"], unique=False)
    op.create_index(op.f("ix_project_snapshots_status"), "project_snapshots", ["status"], unique=False)

    op.create_table(
        "project_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scorer_id", sa.Integer(), nullable=True),
        sa.Column("score_relevance", sa.Float(), nullable=True),
        sa.Column("score_activity", sa.Float(), nullable=True),
        sa.Column("score_influence", sa.Float(), nullable=True),
        sa.Column("score_reproducibility", sa.Float(), nullable=True),
        sa.Column("score_security", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["open_source_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scorer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "weekly_report_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("added_by_id", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("editorial_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["open_source_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_weekly_report_candidates_status"), "weekly_report_candidates", ["status"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_ip", sa.String(length=45), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"], unique=False)

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ui_theme", sa.String(length=50), nullable=True),
        sa.Column("system_theme_sync", sa.Integer(), nullable=True),
        sa.Column("email_notification_enabled", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("user_id", name="uq_user_preference_user"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_index(op.f("ix_audit_logs_request_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_weekly_report_candidates_status"), table_name="weekly_report_candidates")
    op.drop_table("weekly_report_candidates")
    op.drop_table("project_scores")
    op.drop_index(op.f("ix_project_snapshots_status"), table_name="project_snapshots")
    op.drop_index(op.f("ix_project_snapshots_repo_full_name"), table_name="project_snapshots")
    op.drop_index(op.f("ix_project_snapshots_project_id"), table_name="project_snapshots")
    op.drop_index(op.f("ix_project_snapshots_keyword_id"), table_name="project_snapshots")
    op.drop_index(op.f("ix_project_snapshots_collected_at"), table_name="project_snapshots")
    op.drop_table("project_snapshots")
    op.drop_index(op.f("ix_tool_jobs_status"), table_name="tool_jobs")
    op.drop_index(op.f("ix_tool_jobs_job_id"), table_name="tool_jobs")
    op.drop_index("idx_user_created", table_name="tool_jobs")
    op.drop_table("tool_jobs")
    op.drop_index(op.f("ix_forum_reports_status"), table_name="forum_reports")
    op.drop_table("forum_reports")
    op.drop_index(op.f("ix_forum_replies_status"), table_name="forum_replies")
    op.drop_index("idx_thread_created", table_name="forum_replies")
    op.drop_table("forum_replies")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_tools_slug"), table_name="tools")
    op.drop_index(op.f("ix_tools_config_status"), table_name="tools")
    op.drop_table("tools")
    op.drop_index(op.f("ix_forum_threads_status"), table_name="forum_threads")
    op.drop_index(op.f("ix_forum_threads_is_pinned"), table_name="forum_threads")
    op.drop_index(op.f("ix_forum_threads_is_locked"), table_name="forum_threads")
    op.drop_index(op.f("ix_forum_threads_is_featured"), table_name="forum_threads")
    op.drop_index("idx_category_last_replied", table_name="forum_threads")
    op.drop_table("forum_threads")
    op.drop_table("tag_relations")
    op.drop_index(op.f("ix_blog_posts_status"), table_name="blog_posts")
    op.drop_index(op.f("ix_blog_posts_slug"), table_name="blog_posts")
    op.drop_table("blog_posts")
    op.drop_index(op.f("ix_open_source_projects_status"), table_name="open_source_projects")
    op.drop_index(op.f("ix_open_source_projects_repo_full_name"), table_name="open_source_projects")
    op.drop_table("open_source_projects")
    op.drop_index(op.f("ix_discovery_keywords_keyword"), table_name="discovery_keywords")
    op.drop_table("discovery_keywords")
    op.drop_table("tool_manifests")
    op.drop_index(op.f("ix_forum_categories_slug"), table_name="forum_categories")
    op.drop_table("forum_categories")
    op.drop_index(op.f("ix_tags_slug"), table_name="tags")
    op.drop_index(op.f("ix_tags_name"), table_name="tags")
    op.drop_table("tags")
    op.drop_index(op.f("ix_categories_slug"), table_name="categories")
    op.drop_table("categories")
    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    op.drop_table("roles")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
