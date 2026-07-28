"""공통 데이터베이스·저장소·인증 사용자 의존성."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.session import get_session
from app.services.storage_service import StorageService

bearer = HTTPBearer(auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@lru_cache
def get_storage() -> StorageService:
    settings = get_settings()
    return StorageService(settings.data_root, settings.max_upload_size_bytes)


StorageDep = Annotated[StorageService, Depends(get_storage)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise AppError("AUTHENTICATION_REQUIRED", "Authentication is required.", 401)
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise AppError("INVALID_TOKEN", "The access token is invalid or expired.", 401) from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("INVALID_TOKEN", "The access token is invalid or expired.", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
