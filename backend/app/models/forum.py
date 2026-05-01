from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.db.mysql import Base


class ForumCategory(Base):
    __tablename__ = "forum_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    icon = Column(String(50))
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    thread_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    threads = relationship("ForumThread", back_populates="category")


class ForumThread(Base):
    __tablename__ = "forum_threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("forum_categories.id"), nullable=False)
    status = Column(String(20), default="normal", index=True)
    is_pinned = Column(Boolean, default=False, index=True)
    is_featured = Column(Boolean, default=False, index=True)
    is_locked = Column(Boolean, default=False, index=True)
    view_count = Column(Integer, default=0)
    reply_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    last_replied_at = Column(DateTime, nullable=True)
    linked_post_id = Column(Integer, ForeignKey("blog_posts.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_category_last_replied", "category_id", "last_replied_at"),
    )

    author = relationship("User", back_populates="threads")
    category = relationship("ForumCategory", back_populates="threads")
    replies = relationship("ForumReply", back_populates="thread", cascade="all, delete-orphan")
    reports = relationship("ForumReport", back_populates="thread", cascade="all, delete-orphan")
    linked_post = relationship("BlogPost", back_populates="thread")


class ForumReply(Base):
    __tablename__ = "forum_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    thread_id = Column(Integer, ForeignKey("forum_threads.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="normal", index=True)
    like_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_thread_created", "thread_id", "created_at"),
    )

    author = relationship("User", back_populates="replies")
    thread = relationship("ForumThread", back_populates="replies")
    reports = relationship("ForumReport", back_populates="reply", cascade="all, delete-orphan")


class ForumReport(Base):
    __tablename__ = "forum_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    thread_id = Column(Integer, ForeignKey("forum_threads.id", ondelete="CASCADE"), nullable=True)
    reply_id = Column(Integer, ForeignKey("forum_replies.id", ondelete="CASCADE"), nullable=True)
    reason = Column(String(50), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="pending", index=True)
    handler_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    handler_note = Column(Text)
    handled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    thread = relationship("ForumThread", back_populates="reports")
    reply = relationship("ForumReply", back_populates="reports")
