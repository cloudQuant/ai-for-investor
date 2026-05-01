from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: Optional[str] = None
    sort_order: int = 0


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    color: Optional[str] = None


class BlogPostBase(BaseModel):
    title: str = Field(..., max_length=255)
    summary: Optional[str] = None
    content: str
    cover_image_url: Optional[str] = None


class BlogPostCreate(BlogPostBase):
    category_id: Optional[int] = None
    tag_ids: list[int] = []


class BlogPostUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = None
    content: Optional[str] = None
    cover_image_url: Optional[str] = None
    category_id: Optional[int] = None
    tag_ids: Optional[list[int]] = None
    status: Optional[str] = None


class BlogPostResponse(BlogPostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    author_id: int
    author_username: str = ""
    author_avatar: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    status: str
    view_count: int
    like_count: int
    is_pinned: bool
    published_at: Optional[datetime] = None
    created_at: datetime
    tags: list[TagResponse] = []


class BlogPostListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    summary: Optional[str] = None
    author_username: str
    author_avatar: Optional[str] = None
    category_name: Optional[str] = None
    status: str
    view_count: int
    like_count: int
    published_at: Optional[datetime] = None
    created_at: datetime
    tags: list[TagResponse] = []
