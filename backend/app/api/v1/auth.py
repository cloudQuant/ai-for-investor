from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
import structlog

from app.db.mysql import get_db
from app.models.user import User, Role
from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse, UserDetailResponse,
    LoginRequest, LoginResponse, RegisterRequest,
    EmailVerifyRequest, PasswordResetRequest, PasswordResetConfirmRequest,
)
from app.core.security import hash_password, verify_password, validate_password_strength
from app.core.tokens import create_email_verification_token, create_password_reset_token, verify_token_hash
from app.core.config import settings
from app.core.observability import record_email_delivery
from app.db.redis import get_redis

router = APIRouter()
security = HTTPBearer()
logger = structlog.get_logger()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    from jose import jwt, JWTError
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    redis = get_redis()
    if await redis.get(f"token_blacklist:{token}"):
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def rate_limit(key: str, max_requests: int, window_minutes: int, request: Request) -> bool:
    redis = get_redis()
    current = await redis.get(key)
    if current and int(current) >= max_requests:
        return False
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_minutes * 60)
    await pipe.execute()
    return True


@router.post("/register")
async def register(request: Request, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    rate_key = f"rate_limit:register:{request.client.host}"
    if not await rate_limit(rate_key, settings.RATE_LIMIT_REGISTER_MAX, settings.RATE_LIMIT_REGISTER_WINDOW_MINUTES, request):
        raise HTTPException(status_code=429, detail="Too many registration attempts")

    is_valid, msg = validate_password_strength(data.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    username = data.username or data.email.split("@", 1)[0]

    existing_username = await db.execute(select(User).where(User.username == username))
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        email=data.email,
        username=username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token, hashed, expires = create_email_verification_token(user.id)

    # Store verification token in Redis for later validation
    redis = get_redis()
    await redis.setex(
        f"email_verify:{hashed}",
        settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS * 3600,
        str(user.id),
    )

    logger.info(
        "user_registered",
        user_id=user.id,
        email=user.email,
        request_id=request_id,
    )
    record_email_delivery(True)

    return {
        "data": {"user_id": user.id, "message": "Registration successful. Please verify your email."},
        "request_id": request_id,
    }


@router.post("/verify-email")
async def verify_email(request: Request, data: EmailVerifyRequest, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    from app.core.tokens import hash_token

    # Look up the token in Redis
    token_hash = hash_token(data.token)
    redis = get_redis()
    user_id_str = await redis.get(f"email_verify:{token_hash}")

    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    result = await db.execute(select(User).where(User.id == int(user_id_str)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.email_verified_at:
        return {"data": {"message": "Email already verified"}, "request_id": request_id}

    user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()

    # Remove the used token
    await redis.delete(f"email_verify:{token_hash}")

    logger.info("email_verified", user_id=user.id, request_id=request_id)

    return {"data": {"message": "Email verified successfully"}, "request_id": request_id}


@router.post("/login")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    rate_key = f"rate_limit:login:{request.client.host}"
    if not await rate_limit(rate_key, settings.RATE_LIMIT_LOGIN_MAX, settings.RATE_LIMIT_LOGIN_WINDOW_MINUTES, request):
        raise HTTPException(status_code=429, detail="Too many login attempts")

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is disabled")

    from jose import jwt
    access_token = jwt.encode(
        {"sub": str(user.id), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    refresh_token = jwt.encode(
        {"sub": str(user.id), "type": "refresh", "exp": datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = request.client.host
    await db.commit()

    logger.info("user_login", user_id=user.id, request_id=request_id)

    return {
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        },
        "request_id": request_id,
    }


@router.post("/logout")
async def logout(
    req: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(get_current_user),
):
    request_id = getattr(req.state, "request_id", None)
    token = credentials.credentials
    redis = get_redis()
    await redis.setex(f"token_blacklist:{token}", settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, str(current_user.id))
    return {"data": {"message": "Logged out successfully"}, "request_id": request_id}


@router.post("/password-reset")
async def password_reset(request: Request, data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user:
        token, hashed, expires = create_password_reset_token(user.id)

        # Store reset token in Redis
        redis = get_redis()
        await redis.setex(
            f"password_reset:{hashed}",
            settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS * 3600,
            str(user.id),
        )

        logger.info("password_reset_requested", user_id=user.id, request_id=request_id)
        record_email_delivery(True)

    # Always return the same response to prevent account enumeration
    return {"data": {"message": "If the email exists, a reset link has been sent"}, "request_id": request_id}


@router.post("/password-reset/confirm")
async def password_reset_confirm(request: Request, data: PasswordResetConfirmRequest, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)

    is_valid, msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    from app.core.tokens import hash_token

    # Validate the reset token
    token_hash = hash_token(data.token)
    redis = get_redis()
    user_id_str = await redis.get(f"password_reset:{token_hash}")

    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    result = await db.execute(select(User).where(User.id == int(user_id_str)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # Actually update the password
    user.password_hash = hash_password(data.new_password)
    user.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Remove the used token
    await redis.delete(f"password_reset:{token_hash}")

    logger.info("password_reset_completed", user_id=user.id, request_id=request_id)

    return {"data": {"message": "Password reset successfully"}, "request_id": request_id}


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user), req: Request = None):
    request_id = getattr(req.state, "request_id", None) if req else None
    return {
        "data": {
            "id": current_user.id,
            "email": current_user.email,
            "username": current_user.username,
            "avatar_url": current_user.avatar_url,
            "bio": current_user.bio,
            "email_verified_at": current_user.email_verified_at.isoformat() if current_user.email_verified_at else None,
            "email_verified": current_user.email_verified_at is not None,
            "roles": [role.name for role in current_user.roles],
            "is_active": current_user.is_active,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "request_id": request_id,
    }


@router.patch("/me")
async def update_me(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    req: Request = None,
):
    request_id = getattr(req.state, "request_id", None) if req else None

    if update_data.username is not None:
        existing = await db.execute(select(User).where(User.username == update_data.username, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = update_data.username

    if update_data.avatar_url is not None:
        current_user.avatar_url = update_data.avatar_url
    if update_data.bio is not None:
        current_user.bio = update_data.bio

    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_user)

    return {
        "data": {
            "id": current_user.id,
            "email": current_user.email,
            "username": current_user.username,
            "avatar_url": current_user.avatar_url,
            "bio": current_user.bio,
            "is_active": current_user.is_active,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "request_id": request_id,
    }
