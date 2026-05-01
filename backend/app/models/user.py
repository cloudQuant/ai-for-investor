from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, Table, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.db.mysql import Base


class UserRoleEnum(str, enum.Enum):
    GUEST = "guest"
    USER = "user"
    AUTHOR = "author"
    EDITOR = "editor"
    MODERATOR = "moderator"
    ADMIN = "admin"


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("assigned_at", DateTime, default=lambda: datetime.now(timezone.utc)),
    Column("assigned_by", Integer, ForeignKey("users.id")),
)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    permissions = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    users = relationship("User", secondary=user_roles,
                         primaryjoin="Role.id == user_roles.c.role_id",
                         secondaryjoin="User.id == user_roles.c.user_id",
                         back_populates="roles")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    avatar_url = Column(String(500))
    bio = Column(Text)
    email_verified_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    roles = relationship("Role", secondary=user_roles,
                         primaryjoin="User.id == user_roles.c.user_id",
                         secondaryjoin="Role.id == user_roles.c.role_id",
                         back_populates="users")
    posts = relationship("BlogPost", back_populates="author")
    threads = relationship("ForumThread", back_populates="author")
    replies = relationship("ForumReply", back_populates="author")
    tool_jobs = relationship("ToolJob", back_populates="user")
    preferences = relationship("UserPreference", back_populates="user", uselist=False)
