from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class ForumCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    thread_count: int = 0


class ForumThreadBase(BaseModel):
    title: str = Field(..., max_length=255)
    content: str
    category_id: int


class ForumThreadCreate(ForumThreadBase):
    tag_ids: list[int] = []


class ForumThreadUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    category_id: Optional[int] = None
    tag_ids: Optional[list[int]] = None


class ForumThreadResponse(BaseModel):
    id: int
    title: str
    content: str
    category_id: int
    author_id: int
    author_username: str = ""
    author_avatar: Optional[str] = None
    status: str
    is_pinned: bool
    is_featured: bool
    is_locked: bool
    view_count: int
    reply_count: int
    like_count: int
    last_replied_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ForumThreadDetailResponse(ForumThreadResponse):
    tags: list[str] = []


class ForumReplyCreate(BaseModel):
    content: str = Field(..., min_length=1)


class ForumReplyUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class ForumReplyResponse(BaseModel):
    id: int
    content: str
    author_id: int
    author_username: str = ""
    author_avatar: Optional[str] = None
    thread_id: int
    status: str
    like_count: int
    created_at: datetime
    updated_at: datetime


class ForumReportCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    thread_id: Optional[int] = None
    reply_id: Optional[int] = None


class ForumReportStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|reviewing|resolved|rejected)$")
    handler_note: Optional[str] = None


class ForumReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporter_id: int
    thread_id: Optional[int] = None
    reply_id: Optional[int] = None
    reason: str
    description: Optional[str] = None
    status: str
    handler_id: Optional[int] = None
    handler_note: Optional[str] = None
    handled_at: Optional[datetime] = None
    created_at: datetime
