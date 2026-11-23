"""Security-sensitive settings validation."""

import pytest
from pydantic import SecretStr, ValidationError

from xiaoying_quick.bootstrap.settings import Settings


def test_job_heartbeat_interval_defaults_to_one_third_of_lease() -> None:
    from xiaoying_quick.bootstrap.jobs import job_heartbeat_interval

    settings = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        job_lease_seconds=180,
        job_heartbeat_seconds=0,
        job_max_workers=8,
    )
    assert job_heartbeat_interval(settings) == 60.0
    assert job_heartbeat_interval(None) == 5.0
    explicit = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        job_heartbeat_seconds=0.2,
    )
    assert job_heartbeat_interval(explicit) == 0.2


def test_auth_token_ttl_zero_is_never_expire() -> None:
    defaulted = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
    )
    assert defaulted.auth_token_ttl_seconds == 0

    settings = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        auth_token_ttl_seconds=0,
    )
    assert settings.auth_token_ttl_seconds == 0

    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
            auth_token_ttl_seconds=-1,
        )


def test_blank_optional_bootstrap_values_are_disabled() -> None:
    settings = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        bootstrap_admin_username="",
        bootstrap_admin_password="",  # type: ignore[arg-type]
    )
    assert settings.bootstrap_admin_username is None
    assert settings.bootstrap_admin_password is None


def test_production_rejects_development_secret_and_schema_auto_create() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", db_auto_create=True)


def test_sql_approval_secret_is_independent_and_redacted() -> None:
    auth_secret = "auth-secret-with-at-least-thirty-two-bytes"
    sql_secret = "sql-approval-secret-with-at-least-32-bytes"

    settings = Settings(
        environment="test",
        auth_hmac_secret=SecretStr(auth_secret),
        sql_approval_hmac_secret=SecretStr(sql_secret),
    )

    rendered = repr(settings)
    assert auth_secret not in rendered
    assert sql_secret not in rendered
    assert settings.sql_approval_hmac_secret.get_secret_value() == sql_secret


def test_sql_approval_secret_rejects_short_or_reused_auth_key() -> None:
    auth_secret = "auth-secret-with-at-least-thirty-two-bytes"

    with pytest.raises(ValidationError, match="SQL_APPROVAL_HMAC_SECRET"):
        Settings(
            environment="test",
            auth_hmac_secret=SecretStr(auth_secret),
            sql_approval_hmac_secret=SecretStr("too-short"),
        )

    with pytest.raises(ValidationError, match="independent"):
        Settings(
            environment="test",
            auth_hmac_secret=SecretStr(auth_secret),
            sql_approval_hmac_secret=SecretStr(auth_secret),
        )


def test_production_rejects_default_sql_approval_secret() -> None:
    with pytest.raises(ValidationError, match="SQL approval HMAC secret"):
        Settings(
            environment="production",
            database_url="postgresql://db.example/app",
            db_auto_create=False,
            allow_sqlite_data_sources=False,
            auth_hmac_secret=SecretStr("production-auth-secret-with-at-least-32-bytes"),
            master_key=SecretStr("configured-master-key"),
        )


def test_list_settings_accept_json_csv_and_shell_stripped_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS",
        "[rm-uf67.example,amv-uf63.example]",
    )
    monkeypatch.setenv(
        "XIAOYING_CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    stripped = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        sql_approval_hmac_secret=SecretStr("test-sql-secret-with-at-least-32-bytes"),
    )
    assert stripped.data_source_allowed_hosts == ("rm-uf67.example", "amv-uf63.example")
    assert stripped.cors_allowed_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    json_hosts = Settings(
        environment="test",
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        sql_approval_hmac_secret=SecretStr("test-sql-secret-with-at-least-32-bytes"),
        data_source_allowed_hosts='["db.example","lab.example"]',
    )
    assert json_hosts.data_source_allowed_hosts == ("db.example", "lab.example")


def test_production_requires_explicit_data_source_host_allowlist() -> None:
    with pytest.raises(ValidationError, match="DATA_SOURCE_ALLOWED_HOSTS"):
        Settings(
            environment="production",
            database_url="postgresql://db.example/app",
            db_auto_create=False,
            allow_sqlite_data_sources=False,
            auth_hmac_secret=SecretStr("production-auth-secret-with-at-least-32-bytes"),
            sql_approval_hmac_secret=SecretStr("production-sql-secret-with-at-least-32-bytes"),
            master_key=SecretStr("configured-master-key"),
        )


def test_lab_configuration_is_all_or_none_and_uses_complete_endpoint() -> None:
    Settings(
        environment="test",
        lab_endpoint_url="https://lab.example/opentrek-chat/v2/completions",
    )

    with pytest.raises(ValidationError, match="LAB_ENDPOINT_URL"):
        Settings(
            environment="test",
            lab_actual_token=SecretStr("synthetic-actual-token-value"),
        )

    with pytest.raises(ValidationError, match="complete opentrek-chat"):
        _settings_with_labs(lab_endpoint_url="https://lab.example/api")


def test_lab_tokens_and_optional_max_sales_month_are_validated_and_redacted() -> None:
    values = {
        "actual": "synthetic-actual-token-value",
        "demand": "synthetic-demand-token-value",
        "ext_simple": "synthetic-external-simple-token",
        "ext_complex": "synthetic-external-complex-token",
    }
    settings = _settings_with_labs(
        lab_actual_token=SecretStr(values["actual"]),
        lab_demand_token=SecretStr(values["demand"]),
        lab_ext_simple_token=SecretStr(values["ext_simple"]),
        lab_ext_complex_token=SecretStr(values["ext_complex"]),
        lab_max_sales_month="2026-07",
    )

    rendered = repr(settings)
    assert settings.lab_max_sales_month == "2026-07"
    assert all(token not in rendered for token in values.values())

    with pytest.raises(ValidationError, match="YYYY-MM"):
        _settings_with_labs(lab_max_sales_month="2026/07")

    with pytest.raises(ValidationError, match="distinct"):
        _settings_with_labs(lab_demand_token=SecretStr("synthetic-actual-token-value"))


def _settings_with_labs(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "lab_endpoint_url": "https://lab.example/opentrek-chat/v2/completions",
        "lab_actual_token": SecretStr("synthetic-actual-token-value"),
        "lab_demand_token": SecretStr("synthetic-demand-token-value"),
        "lab_ext_simple_token": SecretStr("synthetic-external-simple-token"),
        "lab_ext_complex_token": SecretStr("synthetic-external-complex-token"),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]
