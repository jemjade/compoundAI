"""회원가입·첫 관리자·Mock Parser 초기화·로그인 Workflow."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.parser import ExecutionType
from app.db.models.user import User, UserRole
from app.repositories.parser_repository import ParserRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, SignupRequest
from app.schemas.parser import ParserCreate
from app.services.parser_catalog import parser_catalog_entries


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def signup(self, data: SignupRequest) -> User:
        if await self.users.get_by_email(data.email):
            raise AppError(
                "EMAIL_ALREADY_EXISTS",
                "An account with this email already exists.",
                409,
            )
        is_first_user = await self.users.count() == 0
        role = UserRole.ADMIN if is_first_user else UserRole.USER
        user = await self.users.create(
            data.email,
            hash_password(data.password),
            data.name,
            role,
        )
        if is_first_user:
            await self._seed_mock_parsers(user)
        await self.session.commit()
        return user

    async def _seed_mock_parsers(self, user: User) -> None:
        parsers = ParserRepository(self.session)
        mock_formats = ["pdf", "docx", "pptx", "xlsx", "txt", "md"]
        definitions = [
            ParserCreate(
                name="Mock Standard",
                slug="mock-standard",
                description="원문 구조를 유지하는 Phase 1 내장 Mock Parser",
                provider="ParseLab",
                model_name="Mock Parser",
                model_version="1.0",
                execution_type=ExecutionType.BUILTIN,
                adapter_key="mock_parser",
                default_config={"mode": "standard", "delay_seconds": 0.2},
                capabilities=["TEXT", "MARKDOWN", "LAYOUT"],
                supported_formats=mock_formats,
            ),
            ParserCreate(
                name="Mock Line Reader",
                slug="mock-line-reader",
                description="줄 번호를 추가해 비교 차이를 만드는 Phase 1 내장 Mock Parser",
                provider="ParseLab",
                model_name="Mock Parser",
                model_version="1.0",
                execution_type=ExecutionType.BUILTIN,
                adapter_key="mock_parser",
                default_config={"mode": "line-numbered", "delay_seconds": 0.35},
                capabilities=["TEXT", "MARKDOWN", "LAYOUT"],
                supported_formats=mock_formats,
            ),
        ]
        for definition in definitions:
            await parsers.create(definition, user.id)
        for entry in parser_catalog_entries(get_settings()):
            connector = await parsers.create(entry.definition, user.id)
            connector.is_active = entry.is_active

    async def login(self, data: LoginRequest) -> str:
        user = await self.users.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        if not user.is_active:
            raise AppError("USER_DISABLED", "This account is disabled.", 403)
        return create_access_token(user.id)
