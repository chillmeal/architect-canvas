from __future__ import annotations

from collections.abc import Mapping
from os import environ
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Invalid application configuration: " + "; ".join(errors))


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_env: Literal["local", "test", "production"] = "local"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "sqlite:///./var/data/app.db"
    repository_allowed_roots: tuple[Path, ...] = ()
    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_CORP"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_ca_bundle_file: Path | None = None
    gigachat_model_discovery: str | None = None
    gigachat_model_analysis: str | None = None
    gigachat_model_validation: str | None = None
    gigachat_max_concurrency: int = Field(default=3, ge=1, le=32)
    gigachat_request_timeout_seconds: int = Field(default=120, ge=1, le=600)
    gigachat_verify_ssl_certs: bool = True
    gigachat_allow_insecure_tls_local_debug: bool = False
    audit_max_file_bytes: int = Field(default=1_000_000, ge=1)
    audit_max_input_tokens: int = Field(default=25_000, ge=1)
    audit_max_retries: int = Field(default=3, ge=0, le=10)
    audit_require_clean_git: bool = False
    audit_allow_non_git: bool = False
    confidence_confirmed_min: float = Field(default=0.85, ge=0.0, le=1.0)
    confidence_warnings_min: float = Field(default=0.70, ge=0.0, le=1.0)
    confidence_review_min: float = Field(default=0.40, ge=0.0, le=1.0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_source_content: bool = False

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> Self:
        source = env if env is not None else environ
        raw_config = {
            "app_env": source.get("APP_ENV", "local"),
            "app_host": source.get("APP_HOST", "127.0.0.1"),
            "app_port": source.get("APP_PORT", "8000"),
            "database_url": source.get("DATABASE_URL", "sqlite:///./var/data/app.db"),
            "repository_allowed_roots": source.get("REPOSITORY_ALLOWED_ROOTS", ""),
            "gigachat_credentials": source.get("GIGACHAT_CREDENTIALS") or None,
            "gigachat_scope": source.get("GIGACHAT_SCOPE", "GIGACHAT_API_CORP"),
            "gigachat_base_url": source.get("GIGACHAT_BASE_URL", "https://api.giga.chat/v1"),
            "gigachat_auth_url": source.get(
                "GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
            ),
            "gigachat_ca_bundle_file": source.get("GIGACHAT_CA_BUNDLE_FILE") or None,
            "gigachat_model_discovery": source.get("GIGACHAT_MODEL_DISCOVERY") or None,
            "gigachat_model_analysis": source.get("GIGACHAT_MODEL_ANALYSIS") or None,
            "gigachat_model_validation": source.get("GIGACHAT_MODEL_VALIDATION") or None,
            "gigachat_max_concurrency": source.get("GIGACHAT_MAX_CONCURRENCY", "3"),
            "gigachat_request_timeout_seconds": source.get(
                "GIGACHAT_REQUEST_TIMEOUT_SECONDS", "120"
            ),
            "gigachat_verify_ssl_certs": source.get("GIGACHAT_VERIFY_SSL_CERTS", "true"),
            "gigachat_allow_insecure_tls_local_debug": source.get(
                "GIGACHAT_ALLOW_INSECURE_TLS_LOCAL_DEBUG", "false"
            ),
            "audit_max_file_bytes": source.get("AUDIT_MAX_FILE_BYTES", "1000000"),
            "audit_max_input_tokens": source.get("AUDIT_MAX_INPUT_TOKENS", "25000"),
            "audit_max_retries": source.get("AUDIT_MAX_RETRIES", "3"),
            "audit_require_clean_git": source.get("AUDIT_REQUIRE_CLEAN_GIT", "false"),
            "audit_allow_non_git": source.get("AUDIT_ALLOW_NON_GIT", "false"),
            "confidence_confirmed_min": source.get("CONFIDENCE_CONFIRMED_MIN", "0.85"),
            "confidence_warnings_min": source.get("CONFIDENCE_WARNINGS_MIN", "0.70"),
            "confidence_review_min": source.get("CONFIDENCE_REVIEW_MIN", "0.40"),
            "log_level": source.get("LOG_LEVEL", "INFO").upper(),
            "log_source_content": source.get("LOG_SOURCE_CONTENT", "false"),
        }
        try:
            return cls.model_validate(raw_config)
        except ValueError as exc:
            raise ConfigError(_sanitize_validation_errors(exc)) from exc

    def __repr__(self) -> str:
        values = self.model_dump()
        if values["gigachat_credentials"] is not None:
            values["gigachat_credentials"] = "***"
        return f"AppConfig({values!r})"

    @field_validator("repository_allowed_roots", mode="before")
    @classmethod
    def parse_allowed_roots(cls, value: str | tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
        if isinstance(value, str):
            if not value.strip():
                return ()
            parts = [item.strip() for item in value.split(";") if item.strip()]
            return tuple(Path(item) for item in parts)
        return tuple(value)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL must not be empty")
        if not value.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL is supported in MVP")
        return value

    @field_validator("gigachat_base_url", "gigachat_auth_url")
    @classmethod
    def validate_gigachat_urls(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("GigaChat URLs must be HTTP URLs")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_sensitive_values(self) -> Self:
        errors = []
        if self.app_env == "production" and not self.gigachat_credentials:
            errors.append("GIGACHAT_CREDENTIALS is required in production")
        if self.app_env == "production" and not self.repository_allowed_roots:
            errors.append("REPOSITORY_ALLOWED_ROOTS is required in production")
        if not self.gigachat_verify_ssl_certs and (
            self.app_env != "local" or not self.gigachat_allow_insecure_tls_local_debug
        ):
            errors.append(
                "GIGACHAT_VERIFY_SSL_CERTS=false requires local debug opt-in"
            )
        if self.log_source_content and self.app_env != "local":
            errors.append("LOG_SOURCE_CONTENT=true is allowed only in local")
        if not (
            self.confidence_confirmed_min
            > self.confidence_warnings_min
            > self.confidence_review_min
        ):
            errors.append(
                "confidence thresholds must satisfy confirmed_min > warnings_min > review_min"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def safe_public_dict(self) -> dict[str, object]:
        values = self.model_dump(mode="json")
        if values["gigachat_credentials"] is not None:
            values["gigachat_credentials"] = "***"
        return values


def _sanitize_validation_errors(exc: ValueError) -> list[str]:
    if not hasattr(exc, "errors"):
        return [str(exc).replace("\n", " ")]
    errors = []
    for error in exc.errors():  # type: ignore[attr-defined]
        location = ".".join(str(part) for part in error.get("loc", ())) or "config"
        message = str(error.get("msg", "invalid value"))
        errors.append(f"{location}: {message}")
    return errors
