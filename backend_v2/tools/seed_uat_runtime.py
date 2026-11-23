"""Seed the documented AI_CVRM data source and four Lab domain bindings."""

from __future__ import annotations

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.bootstrap_runtime import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    bootstrap_uat_runtime,
)
from xiaoying_quick.infrastructure.persistence.repositories.data_sources import (
    SqlAlchemyAuditSink,
    SqlAlchemyDataSourceRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.secrets import LocalFernetSecretStore
from xiaoying_quick.infrastructure.source_db import SqlAlchemyConnectionProbe
from xiaoying_quick.modules.data_sources.connection_policy import ConnectionPolicy
from xiaoying_quick.modules.data_sources.service import DataSourceService
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.shared.ids import new_id


def main() -> None:
    settings = Settings()
    engine = build_engine(settings.database_url)
    try:
        store = LocalFernetSecretStore(
            store_path=settings.secret_store_path,
            key_path=settings.secret_key_path,
            key_from_env=(
                settings.master_key.get_secret_value() if settings.master_key else None
            ),
        )
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
            data_sources = DataSourceService(
                SqlAlchemyDataSourceRepository(session),
                store,
                SqlAlchemyConnectionProbe(),
                SqlAlchemyAuditSink(session),
                ConnectionPolicy(
                    allowed_hosts=frozenset(
                        host.lower() for host in settings.data_source_allowed_hosts
                    ),
                    allow_sqlite=settings.allow_sqlite_data_sources,
                ),
                lambda: new_id("ds"),
            )
            report = bootstrap_uat_runtime(
                identity=identity,
                data_sources=data_sources,
                lab_http_configured=settings.lab_endpoint_url is not None,
            )
            print(report.to_record())
            print("login username", ADMIN_USERNAME)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
