from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse, UserDetailResponse,
    LoginRequest, LoginResponse, RegisterRequest,
    EmailVerifyRequest, PasswordResetRequest, PasswordResetConfirmRequest,
)
from app.schemas.blog import (
    CategoryResponse, TagResponse,
    BlogPostCreate, BlogPostUpdate, BlogPostResponse, BlogPostListResponse,
)
from app.schemas.forum import (
    ForumCategoryResponse, ForumThreadCreate, ForumThreadUpdate,
    ForumThreadResponse, ForumThreadDetailResponse,
    ForumReplyCreate, ForumReplyUpdate, ForumReplyResponse,
    ForumReportCreate, ForumReportResponse, ForumReportStatusUpdate,
)
from app.schemas.tool import (
    ToolResponse, ToolDetailResponse, ToolJobCreate, ToolJobResponse, ToolManifestResponse,
)
from app.schemas.discovery import (
    OpenSourceProjectResponse, ProjectScoreUpdate,
    DiscoveryKeywordCreate, WeeklyReportCandidateResponse,
)
from app.schemas.preference import UserPreferenceUpdate, UserPreferenceResponse
