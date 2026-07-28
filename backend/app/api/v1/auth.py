"""회원가입 및 로그인 Endpoint."""

from fastapi import APIRouter, status

from app.api.dependencies import SessionDep
from app.schemas.auth import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupRequest, session: SessionDep) -> UserResponse:
    return UserResponse.model_validate(await AuthService(session).signup(data))


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, session: SessionDep) -> TokenResponse:
    token = await AuthService(session).login(data)
    return TokenResponse(access_token=token)
