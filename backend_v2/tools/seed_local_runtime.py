"""Provision the local AgentLoop schema and bind the local AI_CVRM seed."""

from __future__ import annotations

import os
from pathlib import Path

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.bootstrap_runtime import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    DOMAIN_JOIN_KEYS,
    DOMAIN_TABLES,
    documented_source_objects,
)
from xiaoying_quick.infrastructure.persistence.provision import provision_application_database
from xiaoying_quick.infrastructure.persistence.repositories.data_sources import (
    SqlAlchemyAuditSink,
    SqlAlchemyDataSourceRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
    SqlAlchemyModelConfigRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.secrets import LocalFernetSecretStore
from xiaoying_quick.infrastructure.source_db import SqlAlchemyConnectionProbe
from xiaoying_quick.modules.data_sources.connection_policy import ConnectionPolicy
from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceDraft,
    DataSourceSslMode,
)
from xiaoying_quick.modules.data_sources.service import DataSourceService
from xiaoying_quick.modules.identity.contracts import DataAccessScope
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.modules.models import ModelConfigService
from xiaoying_quick.shared.errors import Conflict
from xiaoying_quick.shared.ids import new_id

LOCAL_SOURCE_NAME = "AI_CVRM 本地实验室查数库"
LOCAL_SOURCE_URL = "mysql+pymysql://127.0.0.1:3306"
LOCAL_SOURCE_USERNAME = "root"
LOCAL_SOURCE_PASSWORD = os.environ.get("GILEAD_LOCAL_SOURCE_PASSWORD", "")
LOCAL_SOURCE_DATABASE = "AI_CVRM"


def main() -> None:
    os.environ.setdefault(
        "XIAOYING_DATABASE_URL",
        "mysql+pymysql://gilead_react_app@127.0.0.1:3306/gilead_agent_loop?charset=utf8mb4",
    )
    os.environ.setdefault(
        "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS",
        "127.0.0.1,localhost",
    )
    settings = Settings()
    report = provision_application_database(settings.database_url)
    print("provision", report.to_record())

    engine = build_engine(settings.database_url)
    store = LocalFernetSecretStore(
        store_path=settings.secret_store_path,
        key_path=settings.secret_key_path,
        key_from_env=settings.master_key.get_secret_value() if settings.master_key else None,
    )
    try:
        with session_scope(build_session_factory(engine)) as session:
            identity = IdentityService(
                SqlAlchemyUserRepository(session),
                PasswordHasher(),
                HMACTokenService(
                    secret=settings.auth_hmac_secret.get_secret_value(),
                    issuer=settings.auth_issuer,
                    ttl_seconds=settings.auth_token_ttl_seconds,
                ),
            )
            try:
                admin = identity.bootstrap_first_admin(
                    username=ADMIN_USERNAME,
                    password=ADMIN_PASSWORD,
                    display_name=ADMIN_USERNAME,
                )
                print("admin_created", admin.id)
            except Conflict:
                admin = identity.authenticate(username=ADMIN_USERNAME, password=ADMIN_PASSWORD)[1]
                print("admin_exists", admin.id)
            if admin.data_scope.mode.value != DataAccessScope.full_access().mode.value:
                identity.configure_data_scope(
                    actor=identity.principal_from_user(admin),
                    user_id=admin.id,
                    scope=DataAccessScope.full_access(),
                )
            service = DataSourceService(
                SqlAlchemyDataSourceRepository(session),
                store,
                SqlAlchemyConnectionProbe(),
                SqlAlchemyAuditSink(session),
                ConnectionPolicy(
                    allowed_hosts=frozenset({"127.0.0.1", "localhost"}),
                    allow_sqlite=True,
                ),
                lambda: new_id("ds"),
            )
            draft = DataSourceDraft(
                name=LOCAL_SOURCE_NAME,
                connection_url=LOCAL_SOURCE_URL,
                username=LOCAL_SOURCE_USERNAME,
                password=LOCAL_SOURCE_PASSWORD,
                selected_database=LOCAL_SOURCE_DATABASE,
                schema=None,
                dialect=DataSourceDialect.MYSQL,
                ssl_mode=DataSourceSslMode.DISABLE,
                allowed_objects=documented_source_objects(),
                query_timeout_seconds=60,
                max_rows=2000,
                allow_private_network=True,
            )
            existing = next((item for item in service.list() if item.name == draft.name), None)
            source = (
                service.create(draft, admin.id)
                if existing is None
                else service.update(existing.id, draft, admin.id)
            )
            test = service.test(source.id, admin.id)
            print("test_ok", test.ok, "errors", test.errors)
            if not test.ok or test.read_only is False:
                raise SystemExit("local AI_CVRM connection test failed")
            revision = service.activate(source.id, admin.id)
            print("revision", revision.id, revision.revision)
            for domain, tables in DOMAIN_TABLES.items():
                binding = service.bind_domain(
                    domain_id=domain,
                    lab_id=domain,
                    revision_id=revision.id,
                    actor_id=admin.id,
                    allowed_objects=tables,
                    allowed_join_keys=DOMAIN_JOIN_KEYS[domain],
                )
                print("bound", binding.domain_id, binding.id)
            models = ModelConfigService(
                SqlAlchemyModelConfigRepository(session),
                store,
                id_factory=lambda: new_id("model"),
            )
            if settings.model_endpoint_url and settings.model_api_key:
                config_name = f"{settings.model_id} 默认配置"
                existing_config = models.active()
                if existing_config is None or existing_config.name != config_name:
                    try:
                        config = models.create(
                            name=config_name,
                            endpoint_url=settings.model_endpoint_url,
                            model_id=settings.model_id,
                            api_key=settings.model_api_key.get_secret_value(),
                            temperature=settings.model_temperature,
                            max_tokens=settings.model_max_tokens,
                            reasoning=settings.model_reasoning,
                            timeout_seconds=settings.model_timeout_seconds,
                            activate=True,
                        )
                        print("model_seeded", config.id, config.model_id)
                    except Conflict:
                        print("model_exists", config_name)
                else:
                    print("model_active", existing_config.id)
            else:
                print("model_skipped", "no model endpoint configured in settings")
    finally:
        engine.dispose()
    print("login", ADMIN_USERNAME, ADMIN_PASSWORD)
    print("sql_seed", Path(__file__).with_name("seed_local_ai_cvrm.sql"))


if __name__ == "__main__":
    main()
