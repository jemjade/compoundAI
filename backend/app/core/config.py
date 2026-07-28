"""환경변수 기반 애플리케이션 설정과 파생 설정값."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "ParseLab"
    database_url: str = "postgresql+asyncpg://parselab:parselab@localhost:5432/parselab"
    jwt_secret: str = "local-development-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 240
    data_root: Path = Path("./data")
    max_upload_size_mb: int = 100
    max_concurrent_runs: int = 2
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    command_allowed_executables: Annotated[list[str], NoDecode] = [
        "docling",
        "uv",
        "docker",
    ]
    synap_api_key: str | None = None
    fasoo_enabled: bool = False
    fasoo_base_url: str | None = None
    fasoo_api_key: str | None = None
    fasoo_timeout_seconds: int = 300
    fasoo_input_type: Literal[
        "ORIGINAL_FILE",
        "TEXT",
        "MARKDOWN",
        "CANONICAL_JSON",
    ] = "TEXT"
    auto_create_tables: bool = True

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("command_allowed_executables", mode="before")
    @classmethod
    def split_executables(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
