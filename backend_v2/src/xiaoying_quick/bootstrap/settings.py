"""Typed process configuration loaded from environment variables."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ..infrastructure.llm.config import ReasoningMode

_DEVELOPMENT_SECRET = "development-only-hmac-secret-change-me"
_DEVELOPMENT_SQL_APPROVAL_SECRET = "development-only-sql-approval-hmac-secret-change-me"
_LAB_TOKEN_FIELDS = (
    "LAB_ACTUAL_TOKEN",
    "LAB_DEMAND_TOKEN",
    "LAB_EXT_SIMPLE_TOKEN",
    "LAB_EXT_COMPLEX_TOKEN",
)
_MAX_SALES_MONTH_PATTERN = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")


class Settings(BaseSettings):
    """Runtime settings.

    Defaults make a local checkout runnable. Production refuses the built-in
    development signing key and must use migrations instead of auto-creation.
    """

    model_config = SettingsConfigDict(
        env_prefix="XIAOYING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = (
        "mysql+pymysql://gilead_react_app@127.0.0.1:3306/gilead_agent_loop?charset=utf8mb4"
    )
    workbook_query_url: SecretStr | None = None
    database_echo: bool = False
    db_auto_create: bool = True
    provision_token: SecretStr | None = None

    auth_hmac_secret: SecretStr = SecretStr(_DEVELOPMENT_SECRET)
    auth_issuer: str = "xiaoying-quick"
    # 0 = never expire. Finite values are 1..86400 seconds.
    auth_token_ttl_seconds: int = Field(default=0, ge=0, le=86_400)
    sql_approval_hmac_secret: SecretStr = SecretStr(_DEVELOPMENT_SQL_APPROVAL_SECRET)

    lab_endpoint_url: str | None = None
    lab_default_provider: Literal["bailian", "bootcamp"] = "bailian"
    lab_bootcamp_endpoint_url: str | None = None
    lab_actual_token: SecretStr | None = None
    lab_demand_token: SecretStr | None = None
    lab_ext_simple_token: SecretStr | None = None
    lab_ext_complex_token: SecretStr | None = None
    lab_timeout_seconds: float = Field(default=30.0, gt=0, le=120.0)
    lab_max_response_bytes: int = Field(
        default=4_000_000,
        ge=1_024,
        le=10 * 1_024 * 1_024,
    )
    lab_max_sales_month: str | None = None
    lab_fallback: Literal["off", "mock"] = "mock"
    lab_fallback_on_error: bool = True
    azai_create_session_url: str | None = None
    azai_run_url: str | None = None
    azai_agent_code: str | None = None
    azai_agent_version: str | None = None
    azai_authorization: SecretStr | None = None
    azai_timeout_seconds: float = Field(default=60.0, gt=0, le=180.0)
    bailian_agent_code: str | None = None
    bailian_authorization: SecretStr | None = None

    model_endpoint_url: str | None = None
    model_api_key: SecretStr | None = None
    model_id: str = "deepseek-v4-flash"
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=300.0)
    model_max_response_bytes: int = Field(
        default=2_000_000,
        ge=1_024,
        le=20 * 1_024 * 1_024,
    )
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    # A reasoning model charges its deliberation against this ceiling before it
    # writes a single character of answer, so the floor is high on purpose:
    # a budget that only fits the reasoning yields an empty completion.
    model_max_tokens: int = Field(default=16_384, ge=2_048, le=65_536)
    # ``off`` by default: on deepseek-v4-flash the deliberation costs seconds and
    # tokens on every call, and the routing/planning prompts already carry the
    # reasoning the model would otherwise rediscover. Flip to ``on`` (or ``auto``
    # for an endpoint that does not know the flag) when the eval says it pays.
    model_reasoning: ReasoningMode = "off"

    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    report_data_label: str | None = None
    report_sample_data: bool = False
    chatbot_mode: Literal["dual", "full", "xlsx"] = "dual"

    secret_store_path: Path = Path("./var/secrets.json")
    secret_key_path: Path = Path("./var/master.key")
    branding_assets_path: Path = Path("./var/branding")
    master_key: SecretStr | None = None
    knowledge_root: Path = Path("../knowledge_gilead")
    knowledge_search_url: str = ""
    knowledge_search_user: str = ""
    knowledge_search_password: SecretStr = SecretStr("")
    knowledge_embedding_url: str = ""
    knowledge_embedding_model: str = "text-embedding-v4"
    knowledge_embedding_key: SecretStr = SecretStr("")
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=4096)
    static_root: Path | None = None
    data_source_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = ()
    allow_sqlite_data_sources: bool = True
    cors_allowed_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    sse_poll_seconds: float = Field(default=0.25, ge=0.05, le=5.0)
    sse_heartbeat_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    job_poll_seconds: float = Field(default=0.5, ge=0.05, le=10.0)
    job_lease_seconds: int = Field(default=180, ge=30, le=3600)
    job_retry_delay_seconds: int = Field(default=2, ge=0, le=300)
    # Concurrent agent loops. Eval and chat share this cap, so leave headroom
    # for an interactive question while a workbook is running.
    job_max_workers: int = Field(default=8, ge=1, le=32)
    # 0 = lease_seconds / 3 (minimum 5s). Tests can set a tiny interval.
    job_heartbeat_seconds: float = Field(default=0, ge=0, le=300)
    database_pool_size: int = Field(default=20, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    # Temporary: skip query-guard / SQL-gate fail-closed and show executed rows
    # as display-only. Tests keep the default on.
    sql_interception: bool = True

    @field_validator(
        "bootstrap_admin_username",
        "bootstrap_admin_password",
        "master_key",
        "lab_endpoint_url",
        "lab_actual_token",
        "lab_demand_token",
        "lab_ext_simple_token",
        "lab_ext_complex_token",
        "lab_max_sales_month",
        "azai_create_session_url",
        "azai_run_url",
        "azai_agent_code",
        "azai_agent_version",
        "azai_authorization",
        "bailian_agent_code",
        "bailian_authorization",
        "model_endpoint_url",
        "model_api_key",
        "provision_token",
        "static_root",
        mode="before",
    )
    @classmethod
    def blank_bootstrap_values_are_disabled(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("data_source_allowed_hosts", "cors_allowed_origins", mode="before")
    @classmethod
    def parse_string_list(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, (list, tuple)):
            return tuple(item.strip() for item in value if str(item).strip())
        text = str(value).strip()
        if not text or text in {"[]", "()"}:
            return ()
        if text[0] in {"[", "("} and text[-1:] in {"]", ")"}:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = [part.strip().strip("'\"") for part in text[1:-1].split(",")]
            else:
                if not isinstance(parsed, list):
                    raise ValueError("list setting must be a JSON array or comma-separated string")
                parsed = [str(item).strip() for item in parsed]
            return tuple(item for item in parsed if item)
        return tuple(part.strip().strip("'\"") for part in text.split(",") if part.strip())

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        secret = self.auth_hmac_secret.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("AUTH_HMAC_SECRET must contain at least 32 bytes")
        sql_approval_secret = self.sql_approval_hmac_secret.get_secret_value()
        if len(sql_approval_secret.encode("utf-8")) < 32:
            raise ValueError("SQL_APPROVAL_HMAC_SECRET must contain at least 32 bytes")
        if sql_approval_secret == secret:
            raise ValueError("SQL approval HMAC secret must be independent from the auth secret")
        if self.environment == "production" and secret == _DEVELOPMENT_SECRET:
            raise ValueError("production cannot use the development HMAC secret")
        if (
            self.environment == "production"
            and sql_approval_secret == _DEVELOPMENT_SQL_APPROVAL_SECRET
        ):
            raise ValueError("production cannot use the development SQL approval HMAC secret")
        if self.environment == "production" and self.db_auto_create:
            raise ValueError("production must use migrations; DB_AUTO_CREATE must be false")
        if self.environment == "production" and self.master_key is None:
            raise ValueError("production must provide MASTER_KEY for the encrypted secret store")
        if self.environment == "production" and self.allow_sqlite_data_sources:
            raise ValueError("production must disable SQLite data sources")
        if self.environment == "production" and not self.data_source_allowed_hosts:
            raise ValueError("production must configure DATA_SOURCE_ALLOWED_HOSTS")
        if self.environment == "production" and self.lab_fallback == "mock":
            raise ValueError("production cannot enable laboratory mock fallback")
        if self.secret_store_path == self.secret_key_path:
            raise ValueError("SECRET_STORE_PATH and SECRET_KEY_PATH must be different")
        if any(origin == "*" for origin in self.cors_allowed_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS cannot contain a wildcard")

        lab_tokens = (
            self.lab_actual_token,
            self.lab_demand_token,
            self.lab_ext_simple_token,
            self.lab_ext_complex_token,
        )
        configured_tokens = tuple(
            value.get_secret_value() for value in lab_tokens if value is not None
        )
        if self.lab_endpoint_url is None:
            if configured_tokens:
                raise ValueError("LAB_ENDPOINT_URL is required when Lab tokens are configured")
            if self.lab_max_sales_month is not None:
                raise ValueError(
                    "LAB_ENDPOINT_URL is required when LAB_MAX_SALES_MONTH is configured"
                )
        else:
            self._validate_lab_endpoint(self.lab_endpoint_url)
            if len(set(configured_tokens)) != len(configured_tokens):
                raise ValueError("Lab tokens must be distinct for each lab_id")
            for token in configured_tokens:
                if (
                    not token
                    or token != token.strip()
                    or not all(0x21 <= ord(character) <= 0x7E for character in token)
                ):
                    raise ValueError("Lab token contains invalid header characters")
        if self.lab_max_sales_month is not None and not _MAX_SALES_MONTH_PATTERN.fullmatch(
            self.lab_max_sales_month
        ):
            raise ValueError("LAB_MAX_SALES_MONTH must use YYYY-MM")

        endpoint_configured = self.model_endpoint_url is not None
        key_configured = self.model_api_key is not None
        if endpoint_configured != key_configured:
            raise ValueError("MODEL_ENDPOINT_URL and MODEL_API_KEY must be set together")
        if endpoint_configured and not self.model_id.strip():
            raise ValueError("MODEL_ID is required when MODEL_ENDPOINT_URL is configured")

        username_configured = bool(self.bootstrap_admin_username)
        password_configured = self.bootstrap_admin_password is not None
        if username_configured != password_configured:
            raise ValueError(
                "BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD must be set together"
            )
        return self

    @staticmethod
    def _validate_lab_endpoint(endpoint_url: str) -> None:
        try:
            parts = urlsplit(endpoint_url)
            hostname = parts.hostname
        except ValueError as error:
            raise ValueError("LAB_ENDPOINT_URL is invalid") from error
        if parts.scheme != "https" or not parts.netloc or not hostname:
            raise ValueError("LAB_ENDPOINT_URL must be an absolute HTTPS URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("LAB_ENDPOINT_URL must not contain credentials, query, or fragment")
        if not parts.path.rstrip("/").endswith("/opentrek-chat/v2/completions"):
            raise ValueError(
                "LAB_ENDPOINT_URL must be the complete opentrek-chat v2 completions URL"
            )
