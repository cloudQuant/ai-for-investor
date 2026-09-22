"""Regression coverage for Iteration 200 SQLAlchemy field typing repairs."""

from sqlalchemy import String, Text

from app.models.audit_record import AuditRecord
from app.models.strategy_explanation import StrategyExplanationModel
from app.models.strategy_score import StrategyScoreModel


def test_mapped_ids_preserve_existing_primary_key_schema() -> None:
    for model in (AuditRecord, StrategyExplanationModel, StrategyScoreModel):
        column = model.__table__.c["id"]

        assert column.name == "id"
        assert isinstance(column.type, String)
        assert column.type.length == 36
        assert column.primary_key
        assert not column.nullable
        assert column.default is not None
        assert column.default.is_callable
        assert column.server_default is None
        assert not column.foreign_keys
        assert not column.unique
        assert not column.index


def test_audit_event_data_preserves_nullable_text_column_schema() -> None:
    column = AuditRecord.__table__.c["event_data"]

    assert column.name == "event_data"
    assert isinstance(column.type, Text)
    assert column.nullable
    assert column.default is None
    assert column.server_default is None
    assert not column.foreign_keys
    assert not column.unique
    assert not column.index
