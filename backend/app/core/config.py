"""환경변수 기반 애플리케이션 설정과 파생 설정값."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
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
    docling_base_url: str | None = None
    docling_api_key: str | None = None
    mineru_base_url: str | None = None
    synap_box_base_url: str | None = None
    synap_chat_base_url: str | None = None
    synap_api_key: str | None = None
    paddleocr_enabled: bool = False
    paddleocr_device: str = "cpu"
    paddleocr_max_concurrency: int = Field(default=1, ge=1, le=8)
    paddleocr_model_cache_dir: Path | None = None
    paddleocr_use_doc_orientation: bool = True
    paddleocr_use_doc_unwarping: bool = True
    paddleocr_use_textline_orientation: bool = True
    paddleocr_use_table_recognition: bool = True
    paddleocr_use_formula_recognition: bool = False
    paddleocr_use_chart_recognition: bool = False
    paddleocr_use_seal_recognition: bool = False
    fasoo_enabled: bool = False
    fasoo_base_url: str | None = None
    fasoo_auth_url: str | None = None
    fasoo_username: str | None = None
    fasoo_password: str | None = None
    fasoo_auth_redirect_url: str = "/commonui"
    fasoo_auth_lang: str = "ko"
    fasoo_api_key: str | None = None
    fasoo_timeout_seconds: int = 300
    fasoo_artifact_wait_seconds: float = 600.0
    fasoo_detect_path: str = "/piiapi/detect/system/path"
    fasoo_configuration_path: str = "/piiapi/configuration"
    nas_mount_path: Path = Path("/app/data/dwp_comp")
    fasoo_nas_path: str = "/dwp_comp"
    fasoo_work_subdir: str = "parselab"
    fasoo_ca_bundle: Path | None = None
    fasoo_patterns: Annotated[list[str], NoDecode] = []
    fasoo_labels: Annotated[list[str], NoDecode] = []
    fasoo_rule_json: str | None = None
    fasoo_masking_char: str = "*"
    fasoo_rule_version: str = "1.3"
    fasoo_system_code: str = "FASOO"
    fasoo_system_name: str = "파수"
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

    @field_validator("fasoo_patterns", "fasoo_labels", mode="before")
    @classmethod
    def split_fasoo_policy_values(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fasoo_ca_bundle", mode="before")
    @classmethod
    def blank_ca_bundle_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("paddleocr_model_cache_dir", mode="before")
    @classmethod
    def blank_paddleocr_cache_dir_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "docling_base_url",
        "mineru_base_url",
        "synap_box_base_url",
        "synap_chat_base_url",
        "synap_api_key",
        "fasoo_auth_url",
        "fasoo_username",
        "fasoo_password",
        "fasoo_api_key",
        mode="before",
    )
    @classmethod
    def blank_optional_string_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("paddleocr_device")
    @classmethod
    def validate_paddleocr_device(cls, value: str) -> str:
        if value == "cpu":
            return value
        if value == "gpu":
            return value
        if value.startswith("gpu:"):
            device_ids = value.removeprefix("gpu:").split(",")
            if device_ids and all(item.isdigit() for item in device_ids):
                return value
        raise ValueError("PADDLEOCR_DEVICE must be cpu, gpu, or gpu:<device-id>.")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
