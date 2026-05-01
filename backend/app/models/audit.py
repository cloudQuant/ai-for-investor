from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON
from datetime import datetime, timezone

from app.db.mysql import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_ip = Column(String(45))
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=True)
    changes = Column(JSON)
    request_id = Column(String(50), index=True)
    user_agent = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
