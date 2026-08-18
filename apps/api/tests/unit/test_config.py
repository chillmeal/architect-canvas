from pathlib import Path

import pytest

from app.core.config import AppConfig, ConfigError


def test_config_loads_defaults() -> None:
    config = AppConfig.from_environment({})

    assert config.app_env == "local"
    assert config.app_host == "127.0.0.1"
    assert config.app_port == 8000
    assert config.database_url == "sqlite:///./var/data/app.db"
    assert config.repository_allowed_roots == ()
    assert config.gigachat_auth_url == "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    assert config.gigachat_ca_bundle_file is None
    assert config.gigachat_max_concurrency == 3
    assert config.gigachat_verify_ssl_certs is True
    assert config.confidence_confirmed_min == 0.85
    assert config.confidence_warnings_min == 0.70
    assert config.confidence_review_min == 0.40


def test_config_loads_environment_overrides() -> None:
    config = AppConfig.from_environment(
        {
            "APP_ENV": "test",
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "9000",
            "DATABASE_URL": "sqlite:///./var/data/test.db",
            "REPOSITORY_ALLOWED_ROOTS": "/work/repos;/tmp/fixtures",
            "GIGACHAT_CREDENTIALS": "super-secret",
            "GIGACHAT_AUTH_URL": "https://auth.example.test/oauth",
            "GIGACHAT_CA_BUNDLE_FILE": "/work/certs/giga.pem",
            "GIGACHAT_MAX_CONCURRENCY": "1",
            "GIGACHAT_REQUEST_TIMEOUT_SECONDS": "30",
            "GIGACHAT_ALLOW_INSECURE_TLS_LOCAL_DEBUG": "true",
            "AUDIT_MAX_FILE_BYTES": "42",
            "AUDIT_REQUIRE_CLEAN_GIT": "true",
            "AUDIT_ALLOW_NON_GIT": "true",
            "CONFIDENCE_CONFIRMED_MIN": "0.9",
            "CONFIDENCE_WARNINGS_MIN": "0.75",
            "CONFIDENCE_REVIEW_MIN": "0.5",
            "LOG_LEVEL": "debug",
        }
    )

    assert config.app_env == "test"
    assert config.app_port == 9000
    assert config.repository_allowed_roots == (Path("/work/repos"), Path("/tmp/fixtures"))
    assert config.gigachat_credentials is not None
    assert config.gigachat_credentials.get_secret_value() == "super-secret"
    assert config.gigachat_auth_url == "https://auth.example.test/oauth"
    assert config.gigachat_ca_bundle_file == Path("/work/certs/giga.pem")
    assert config.gigachat_max_concurrency == 1
    assert config.audit_require_clean_git is True
    assert config.audit_allow_non_git is True
    assert config.confidence_confirmed_min == 0.9
    assert config.confidence_warnings_min == 0.75
    assert config.confidence_review_min == 0.5
    assert config.log_level == "DEBUG"


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ConfigError) as exc_info:
        AppConfig.from_environment({"APP_PORT": "not-a-port"})

    assert "app_port" in str(exc_info.value)
    assert "not-a-port" not in str(exc_info.value)


def test_config_rejects_unsafe_production_values() -> None:
    with pytest.raises(ConfigError) as exc_info:
        AppConfig.from_environment(
            {
                "APP_ENV": "production",
                "GIGACHAT_VERIFY_SSL_CERTS": "false",
                "LOG_SOURCE_CONTENT": "true",
            }
        )

    message = str(exc_info.value)
    assert "GIGACHAT_CREDENTIALS is required in production" in message
    assert "REPOSITORY_ALLOWED_ROOTS is required in production" in message
    assert "GIGACHAT_VERIFY_SSL_CERTS=false requires local debug opt-in" in message


def test_config_rejects_invalid_confidence_threshold_order() -> None:
    with pytest.raises(ConfigError) as exc_info:
        AppConfig.from_environment(
            {
                "CONFIDENCE_CONFIRMED_MIN": "0.70",
                "CONFIDENCE_WARNINGS_MIN": "0.85",
                "CONFIDENCE_REVIEW_MIN": "0.40",
            }
        )

    assert "confidence thresholds" in str(exc_info.value)


def test_config_repr_and_public_dict_mask_secrets() -> None:
    config = AppConfig.from_environment({"GIGACHAT_CREDENTIALS": "super-secret"})

    assert "super-secret" not in repr(config)
    assert config.safe_public_dict()["gigachat_credentials"] == "***"
