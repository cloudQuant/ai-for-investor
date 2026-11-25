"""Legacy runtime schema-compatibility helpers extracted from ``app.db.database``.

Kept separate from engine/session pooling lifecycle so ``database.py`` stays
focused and under the production file-size ratchet.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy import Table, text

logger = logging.getLogger(__name__)


def _create_table_if_missing(from_clause: sa.FromClause, bind) -> None:
    """Create one declared table when the clause is a concrete Table."""
    if isinstance(from_clause, Table):
        from_clause.create(bind=bind, checkfirst=True)


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _get_column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _get_index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _add_column_if_missing(bind, table_name: str, column_name: str, ddl: str) -> bool:
    if not _has_table(bind, table_name):
        return False
    if column_name in _get_column_names(bind, table_name):
        return False

    bind.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
    logger.warning(
        "Added missing database column %s.%s during startup schema sync", table_name, column_name
    )
    return True


def _ensure_index_if_missing(bind, table_name: str, index_name: str, column_name: str) -> None:
    _ensure_index_columns_if_missing(bind, table_name, index_name, (column_name,))


def _ensure_index_columns_if_missing(
    bind,
    table_name: str,
    index_name: str,
    column_names: tuple[str, ...],
) -> None:
    if not _has_table(bind, table_name):
        return
    if index_name in _get_index_names(bind, table_name):
        return

    metadata = sa.MetaData()
    table = sa.Table(table_name, metadata, autoload_with=bind)
    sa.Index(index_name, *(table.c[column_name] for column_name in column_names)).create(bind=bind)
    logger.warning(
        "Added missing database index %s on %s(%s)",
        index_name,
        table_name,
        ", ".join(column_names),
    )


def _modify_mysql_column_type_if_needed(
    bind,
    table_name: str,
    column_name: str,
    ddl: str,
    expected_type_fragment: str,
) -> None:
    if bind.dialect.name != "mysql" or not _has_table(bind, table_name):
        return

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table_name)}
    column = columns.get(column_name)
    if column is None:
        return

    current_type = str(column["type"]).upper()
    if expected_type_fragment.upper() in current_type:
        return

    bind.execute(text(f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {ddl}"))
    logger.warning(
        "Modified MySQL column %s.%s to %s during startup schema sync",
        table_name,
        column_name,
        ddl,
    )


def _make_column_nullable_if_needed(
    bind,
    table_name: str,
    column_name: str,
    ddl: str,
) -> None:
    if not _has_table(bind, table_name):
        return

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table_name)}
    column = columns.get(column_name)
    if column is None or column.get("nullable", True):
        return

    dialect_name = bind.dialect.name
    if dialect_name == "mysql":
        bind.execute(text(f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {ddl}"))
    elif dialect_name == "postgresql":
        bind.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL"))
    elif dialect_name == "sqlite" and table_name == "chat_conversations":
        _rebuild_sqlite_chat_conversations_with_nullable_kb(bind)
    else:
        logger.warning(
            "Cannot automatically make %s.%s nullable for dialect %s",
            table_name,
            column_name,
            dialect_name,
        )
        return

    logger.warning(
        "Made database column %s.%s nullable during startup schema sync",
        table_name,
        column_name,
    )


def _rebuild_sqlite_chat_conversations_with_nullable_kb(bind) -> None:
    """Rebuild SQLite chat_conversations so knowledge_base_id can be NULL."""
    bind.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        bind.execute(text("DROP TABLE IF EXISTS chat_conversations_new"))
        bind.execute(
            text(
                """
                CREATE TABLE chat_conversations_new (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    knowledge_base_id VARCHAR(36),
                    user_id VARCHAR(36) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    model_id VARCHAR(200),
                    settings JSON,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
        )
        existing_columns = _get_column_names(bind, "chat_conversations")
        copy_columns = [
            column
            for column in (
                "id",
                "knowledge_base_id",
                "user_id",
                "title",
                "model_id",
                "settings",
                "created_at",
                "updated_at",
            )
            if column in existing_columns
        ]
        if copy_columns:
            columns_sql = ", ".join(copy_columns)
            bind.execute(
                text(
                    f"INSERT INTO chat_conversations_new ({columns_sql}) "
                    f"SELECT {columns_sql} FROM chat_conversations"
                )
            )
        bind.execute(text("DROP TABLE chat_conversations"))
        bind.execute(text("ALTER TABLE chat_conversations_new RENAME TO chat_conversations"))
        bind.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_conversations_knowledge_base_id "
                "ON chat_conversations (knowledge_base_id)"
            )
        )
        bind.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_id "
                "ON chat_conversations (user_id)"
            )
        )
    finally:
        bind.execute(text("PRAGMA foreign_keys=ON"))


def _ensure_workspace_schema_compatibility_sync(bind) -> None:
    dialect_name = bind.dialect.name
    false_literal = "FALSE" if dialect_name == "postgresql" else "0"

    if _has_table(bind, "workspaces"):
        _add_column_if_missing(
            bind,
            "workspaces",
            "workspace_type",
            "workspace_type VARCHAR(32) NOT NULL DEFAULT 'research'",
        )
        _add_column_if_missing(
            bind,
            "workspaces",
            "trading_config",
            "trading_config JSON",
        )
        if "workspace_type" in _get_column_names(bind, "workspaces"):
            bind.execute(
                text(
                    "UPDATE workspaces SET workspace_type = 'research' WHERE workspace_type IS NULL"
                )
            )
            _ensure_index_if_missing(
                bind,
                "workspaces",
                "ix_workspaces_workspace_type",
                "workspace_type",
            )
            _ensure_index_columns_if_missing(
                bind,
                "workspaces",
                "ix_workspaces_user_type_updated_id",
                ("user_id", "workspace_type", "updated_at", "id"),
            )
            _ensure_index_columns_if_missing(
                bind,
                "workspaces",
                "ix_workspaces_user_updated_id",
                ("user_id", "updated_at", "id"),
            )

    if _has_table(bind, "strategy_units"):
        _add_column_if_missing(
            bind,
            "strategy_units",
            "trading_mode",
            "trading_mode VARCHAR(20) NOT NULL DEFAULT 'paper'",
        )
        _add_column_if_missing(
            bind,
            "strategy_units",
            "gateway_config",
            "gateway_config JSON",
        )
        _add_column_if_missing(
            bind,
            "strategy_units",
            "lock_trading",
            f"lock_trading BOOLEAN NOT NULL DEFAULT {false_literal}",
        )
        _add_column_if_missing(
            bind,
            "strategy_units",
            "lock_running",
            f"lock_running BOOLEAN NOT NULL DEFAULT {false_literal}",
        )
        _add_column_if_missing(
            bind,
            "strategy_units",
            "trading_instance_id",
            "trading_instance_id VARCHAR(36)",
        )
        _add_column_if_missing(
            bind,
            "strategy_units",
            "trading_snapshot",
            "trading_snapshot JSON",
        )

        unit_columns = _get_column_names(bind, "strategy_units")
        if "trading_mode" in unit_columns:
            bind.execute(
                text("UPDATE strategy_units SET trading_mode = 'paper' WHERE trading_mode IS NULL")
            )
        if "lock_trading" in unit_columns:
            bind.execute(
                text(
                    f"UPDATE strategy_units SET lock_trading = {false_literal} "
                    "WHERE lock_trading IS NULL"
                )
            )
        if "lock_running" in unit_columns:
            bind.execute(
                text(
                    f"UPDATE strategy_units SET lock_running = {false_literal} "
                    "WHERE lock_running IS NULL"
                )
            )


def _ensure_knowledge_base_schema_compatibility_sync(bind) -> None:
    """Create or patch tables used by the knowledge-base and AI chat modules."""
    from app.models.knowledge_base import (
        ChatConversation,
        ChatMessage,
        DocumentChunk,
        KBDocument,
        KnowledgeBase,
        ModelConfig,
        ModelUsageLog,
    )

    for table in (
        KnowledgeBase.__table__,
        KBDocument.__table__,
        DocumentChunk.__table__,
        ChatConversation.__table__,
        ChatMessage.__table__,
        ModelConfig.__table__,
        ModelUsageLog.__table__,
    ):
        _create_table_if_missing(table, bind)

    dialect_name = bind.dialect.name
    json_type = "JSON"
    datetime_type = "TIMESTAMP" if dialect_name == "postgresql" else "DATETIME"

    _add_column_if_missing(
        bind,
        "chat_conversations",
        "user_id",
        "user_id VARCHAR(36)",
    )
    _add_column_if_missing(
        bind,
        "chat_conversations",
        "model_id",
        "model_id VARCHAR(200)",
    )
    _add_column_if_missing(
        bind,
        "chat_conversations",
        "settings",
        f"settings {json_type}",
    )
    _add_column_if_missing(
        bind,
        "chat_conversations",
        "created_at",
        f"created_at {datetime_type}",
    )
    _add_column_if_missing(
        bind,
        "chat_conversations",
        "updated_at",
        f"updated_at {datetime_type}",
    )
    _make_column_nullable_if_needed(
        bind,
        "chat_conversations",
        "knowledge_base_id",
        "VARCHAR(36) NULL",
    )

    if _has_table(bind, "chat_messages"):
        _add_column_if_missing(bind, "chat_messages", "citations", f"citations {json_type}")
        _add_column_if_missing(bind, "chat_messages", "tokens_used", "tokens_used INTEGER")
        _add_column_if_missing(bind, "chat_messages", "model_id", "model_id VARCHAR(200)")
        _add_column_if_missing(bind, "chat_messages", "reasoning", "reasoning TEXT")
        _add_column_if_missing(bind, "chat_messages", "metadata", f"metadata {json_type}")
        _add_column_if_missing(bind, "chat_messages", "created_at", f"created_at {datetime_type}")

    _modify_mysql_column_type_if_needed(
        bind, "kb_documents", "content", "LONGTEXT NULL", "LONGTEXT"
    )
    _modify_mysql_column_type_if_needed(
        bind, "document_chunks", "content", "LONGTEXT NOT NULL", "LONGTEXT"
    )
    _modify_mysql_column_type_if_needed(
        bind, "chat_messages", "content", "LONGTEXT NOT NULL", "LONGTEXT"
    )
    _modify_mysql_column_type_if_needed(
        bind, "chat_messages", "reasoning", "LONGTEXT NULL", "LONGTEXT"
    )


def _ensure_airflow_schema_compatibility_sync(bind) -> None:
    """Add Airflow-related columns to ak_task_executions if missing."""
    if _has_table(bind, "ak_task_executions"):
        _add_column_if_missing(
            bind, "ak_task_executions", "airflow_dag_id", "airflow_dag_id VARCHAR(200)"
        )
        _add_column_if_missing(
            bind, "ak_task_executions", "airflow_run_id", "airflow_run_id VARCHAR(200)"
        )
        _add_column_if_missing(
            bind, "ak_task_executions", "airflow_task_id", "airflow_task_id VARCHAR(200)"
        )


def _ensure_ai_budget_schema_compatibility_sync(bind) -> None:
    if _has_table(bind, "users"):
        _add_column_if_missing(bind, "users", "ai_budget_daily_usd", "ai_budget_daily_usd FLOAT")
        _add_column_if_missing(bind, "users", "ai_budget_mode", "ai_budget_mode VARCHAR(20)")
        _add_column_if_missing(
            bind, "users", "ai_preferred_provider", "ai_preferred_provider VARCHAR(50)"
        )
        _add_column_if_missing(
            bind, "users", "ai_preferred_model", "ai_preferred_model VARCHAR(100)"
        )


def _ensure_prompt_template_schema_compatibility_sync(bind) -> None:
    from app.models.prompt_template import PromptTemplate

    _create_table_if_missing(PromptTemplate.__table__, bind)
    _add_column_if_missing(
        bind,
        "prompt_templates",
        "rollout_percentage",
        "rollout_percentage INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        bind,
        "ai_call_logs",
        "prompt_template_version",
        "prompt_template_version VARCHAR(50)",
    )
    _ensure_index_if_missing(
        bind,
        "ai_call_logs",
        "ix_ai_call_logs_prompt_template_version",
        "prompt_template_version",
    )


def _ensure_broker_profiles_schema_compatibility_sync(bind) -> None:
    if _has_table(bind, "broker_connection_profiles"):
        _add_column_if_missing(
            bind,
            "broker_connection_profiles",
            "runtime_gateway_key",
            "runtime_gateway_key VARCHAR(120)",
        )
        _add_column_if_missing(
            bind,
            "broker_connection_profiles",
            "runtime_account_id",
            "runtime_account_id VARCHAR(100)",
        )
        _ensure_index_if_missing(
            bind,
            "broker_connection_profiles",
            "ix_broker_connection_profiles_runtime_gateway_key",
            "runtime_gateway_key",
        )


def _ensure_portfolio_ledger_schema_compatibility_sync(bind) -> None:
    from app.models.portfolio_ledger import (
        PortfolioLedgerImportModel,
        PortfolioLedgerModel,
        PortfolioLedgerSnapshotModel,
        PortfolioLedgerTransactionModel,
    )

    for table in (
        PortfolioLedgerModel.__table__,
        PortfolioLedgerImportModel.__table__,
        PortfolioLedgerTransactionModel.__table__,
        PortfolioLedgerSnapshotModel.__table__,
    ):
        _create_table_if_missing(table, bind)


def _ensure_news_intelligence_schema_compatibility_sync(bind) -> None:
    from app.models.news_intelligence import (
        NewsAnalysisModel,
        NewsArticleModel,
        NewsSourceModel,
    )

    for table in (
        NewsSourceModel.__table__,
        NewsArticleModel.__table__,
        NewsAnalysisModel.__table__,
    ):
        _create_table_if_missing(table, bind)

    _add_column_if_missing(bind, "news_articles", "content", "content TEXT NULL")


def _ensure_stock_analysis_schema_compatibility_sync(bind) -> None:
    from app.models.stock_analysis import (
        StockAnalysisExportModel,
        StockAnalysisReportModel,
        StockAnalysisTaskModel,
    )

    for table in (
        StockAnalysisTaskModel.__table__,
        StockAnalysisReportModel.__table__,
        StockAnalysisExportModel.__table__,
    ):
        _create_table_if_missing(table, bind)


def _ensure_scanner_plan_schema_compatibility_sync(bind) -> None:
    from app.models.scanner_plan import ScannerPlanModel, ScannerPlanRunModel

    for table in (
        ScannerPlanModel.__table__,
        ScannerPlanRunModel.__table__,
    ):
        _create_table_if_missing(table, bind)

    if _has_table(bind, "scanner_plans"):
        _add_column_if_missing(
            bind,
            "scanner_plans",
            "result_table_name",
            "result_table_name VARCHAR(120)",
        )
        _add_column_if_missing(
            bind,
            "scanner_plans",
            "result_table_status",
            "result_table_status VARCHAR(20) DEFAULT 'missing' NOT NULL",
        )
        _ensure_index_if_missing(
            bind,
            "scanner_plans",
            "ix_scanner_plans_result_table_name",
            "result_table_name",
        )


_AKSHARE_LEGACY_ENUM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ak_data_scripts", "frequency"),
    ("ak_interface_parameters", "param_type"),
    ("ak_scheduled_tasks", "schedule_type"),
    ("ak_task_executions", "status"),
    ("ak_task_executions", "triggered_by"),
)


def _ensure_akshare_mgmt_schema_compatibility_sync(bind) -> None:
    """Normalize legacy uppercase akshare enum labels to lowercase values."""
    dialect_name = bind.dialect.name
    normalized_postgres_enum_types: set[tuple[str | None, str]] = set()
    for table_name, column_name in _AKSHARE_LEGACY_ENUM_COLUMNS:
        if not _has_table(bind, table_name):
            continue
        columns = {column["name"]: column for column in sa.inspect(bind).get_columns(table_name)}
        column = columns.get(column_name)
        if column is None:
            continue

        if dialect_name == "mysql":
            enum_labels = list(getattr(column["type"], "enums", []) or [])
            if not enum_labels or all(label == label.lower() for label in enum_labels):
                continue
            labels_sql = ", ".join(f"'{label.lower()}'" for label in enum_labels)
            null_sql = "NULL" if column.get("nullable", True) else "NOT NULL"
            bind.execute(
                text(
                    f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} "
                    f"ENUM({labels_sql}) {null_sql}"
                )
            )
            logger.warning(
                "Normalized MySQL enum column %s.%s to lowercase values during startup schema sync",
                table_name,
                column_name,
            )
            continue

        if dialect_name == "postgresql":
            enum_labels = list(getattr(column["type"], "enums", []) or [])
            enum_type_name = getattr(column["type"], "name", None)
            if enum_labels:
                if not enum_type_name:
                    logger.warning(
                        "Skipped PostgreSQL enum normalization for %s.%s: enum type has no name",
                        table_name,
                        column_name,
                    )
                    continue

                rename_pairs = [
                    (label, label.lower()) for label in enum_labels if label != label.lower()
                ]
                if not rename_pairs:
                    continue

                enum_schema = getattr(column["type"], "schema", None)
                enum_key = (enum_schema, enum_type_name)
                if enum_key in normalized_postgres_enum_types:
                    continue

                existing_labels = set(enum_labels)
                if any(new_label in existing_labels for _, new_label in rename_pairs):
                    logger.warning(
                        "Skipped PostgreSQL enum normalization for %s.%s: lower-case labels already exist",
                        table_name,
                        column_name,
                    )
                    continue

                quote_identifier = bind.dialect.identifier_preparer.quote
                enum_sql = quote_identifier(enum_type_name)
                if enum_schema:
                    enum_sql = f"{quote_identifier(enum_schema)}.{enum_sql}"
                for old_label, new_label in rename_pairs:
                    old_sql = old_label.replace("'", "''")
                    new_sql = new_label.replace("'", "''")
                    bind.execute(
                        text(f"ALTER TYPE {enum_sql} RENAME VALUE '{old_sql}' TO '{new_sql}'")
                    )
                normalized_postgres_enum_types.add(enum_key)
                logger.warning(
                    "Normalized PostgreSQL enum type %s to lowercase values during startup schema sync",
                    enum_sql,
                )
                continue

        updated = bind.execute(
            text(
                f"UPDATE {table_name} SET {column_name} = LOWER({column_name}) "
                f"WHERE {column_name} <> LOWER({column_name})"
            )
        ).rowcount
        if updated:
            logger.warning(
                "Normalized %d legacy uppercase enum value(s) in %s.%s during startup schema sync",
                updated,
                table_name,
                column_name,
            )


def _ensure_trading_schema_compatibility_sync(bind) -> None:
    """Patch legacy trading tables that ``create_all`` cannot alter in place."""
    for column_name, ddl in (
        ("average_holding_bars", "average_holding_bars FLOAT"),
        ("max_consecutive_wins", "max_consecutive_wins INTEGER"),
        ("max_consecutive_losses", "max_consecutive_losses INTEGER"),
        ("profit_loss_ratio", "profit_loss_ratio FLOAT"),
        ("standard_metrics", "standard_metrics JSON"),
        ("result_summary", "result_summary JSON"),
    ):
        _add_column_if_missing(bind, "backtest_results", column_name, ddl)

    for column_name, ddl in (
        ("margin_value", "margin_value FLOAT NOT NULL DEFAULT 0"),
        ("multiplier", "multiplier FLOAT NOT NULL DEFAULT 1"),
        ("margin_rate", "margin_rate FLOAT NOT NULL DEFAULT 1"),
        ("commission_rate", "commission_rate FLOAT NOT NULL DEFAULT 0"),
        ("commission_amount", "commission_amount FLOAT NOT NULL DEFAULT 0"),
    ):
        _add_column_if_missing(bind, "paper_trading_positions", column_name, ddl)

    for table_name, column_name in (
        ("paper_trading_positions", "size"),
        ("paper_trading_orders", "size"),
        ("paper_trading_orders", "filled_size"),
        ("paper_trades", "size"),
    ):
        _modify_mysql_column_type_if_needed(
            bind, table_name, column_name, "FLOAT NOT NULL", "FLOAT"
        )

    for column_name, ddl in (
        ("workspace_id", "workspace_id VARCHAR(36)"),
        ("unit_id", "unit_id VARCHAR(36)"),
        ("instance_id", "instance_id VARCHAR(36)"),
        ("dedupe_key", "dedupe_key VARCHAR(200)"),
    ):
        _add_column_if_missing(bind, "alerts", column_name, ddl)


def run_all_schema_compatibility_sync(bind) -> None:
    """Apply all legacy compatibility schema patches on a sync SQLAlchemy connection."""
    for helper in (
        _ensure_workspace_schema_compatibility_sync,
        _ensure_knowledge_base_schema_compatibility_sync,
        _ensure_airflow_schema_compatibility_sync,
        _ensure_ai_budget_schema_compatibility_sync,
        _ensure_prompt_template_schema_compatibility_sync,
        _ensure_broker_profiles_schema_compatibility_sync,
        _ensure_portfolio_ledger_schema_compatibility_sync,
        _ensure_news_intelligence_schema_compatibility_sync,
        _ensure_stock_analysis_schema_compatibility_sync,
        _ensure_scanner_plan_schema_compatibility_sync,
        _ensure_akshare_mgmt_schema_compatibility_sync,
        _ensure_trading_schema_compatibility_sync,
    ):
        helper(bind)
