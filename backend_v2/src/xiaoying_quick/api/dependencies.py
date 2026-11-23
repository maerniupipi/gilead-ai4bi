"""FastAPI dependency wiring for the initial identity/run slice."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.repositories.data_sources import (
    SqlAlchemyAuditSink,
    SqlAlchemyDataSourceRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.knowledge import (
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyPersonalMemoryRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.secrets.fernet_store import LocalFernetSecretStore
from xiaoying_quick.modules.data_sources.connection_policy import ConnectionPolicy
from xiaoying_quick.modules.data_sources.ports import (
    ConnectionProbe,
    DataSourceRepository,
    SecretStore,
)
from xiaoying_quick.modules.data_sources.service import DataSourceService
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, Role
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.modules.knowledge.content_guard import KnowledgeContentGuard
from xiaoying_quick.modules.knowledge.ports import KnowledgeIndexPort
from xiaoying_quick.modules.knowledge.service import (
    KnowledgeGovernanceService,
    PersonalMemoryService,
)
from xiaoying_quick.modules.runs.service import RunService
from xiaoying_quick.shared.errors import AuthenticationFailed, Forbidden
from xiaoying_quick.shared.ids import new_id

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_db_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db_session, scope="function")]


def get_identity_service(request: Request, session: DbSession) -> IdentityService:
    return IdentityService(
        SqlAlchemyUserRepository(session),
        request.app.state.password_hasher,
        request.app.state.token_service,
        audit=SqlAlchemyAuditSink(session),
    )


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]


def get_run_service(session: DbSession) -> RunService:
    return RunService(SqlAlchemyRunRepository(session))


RunServiceDep = Annotated[RunService, Depends(get_run_service)]


def get_secret_store(request: Request) -> SecretStore:
    existing = request.app.state.secret_store
    if existing is not None:
        return cast(SecretStore, existing)
    lock = cast(threading.Lock, request.app.state.secret_store_lock)
    with lock:
        existing = request.app.state.secret_store
        if existing is None:
            settings = get_settings(request)
            existing = LocalFernetSecretStore(
                store_path=settings.secret_store_path,
                key_path=settings.secret_key_path,
                key_from_env=(
                    settings.master_key.get_secret_value() if settings.master_key else None
                ),
            )
            request.app.state.secret_store = existing
    return cast(SecretStore, existing)


SecretStoreDep = Annotated[SecretStore, Depends(get_secret_store)]


def get_data_source_repository(session: DbSession) -> DataSourceRepository:
    return SqlAlchemyDataSourceRepository(session)


DataSourceRepositoryDep = Annotated[DataSourceRepository, Depends(get_data_source_repository)]


def get_data_source_service(
    request: Request,
    session: DbSession,
    secret_store: SecretStoreDep,
) -> DataSourceService:
    settings = get_settings(request)
    return DataSourceService(
        SqlAlchemyDataSourceRepository(session),
        secret_store,
        cast(ConnectionProbe, request.app.state.connection_probe),
        SqlAlchemyAuditSink(session),
        ConnectionPolicy(
            allowed_hosts=frozenset(host.lower() for host in settings.data_source_allowed_hosts),
            allow_sqlite=settings.allow_sqlite_data_sources,
        ),
        lambda: new_id("ds"),
    )


DataSourceServiceDep = Annotated[DataSourceService, Depends(get_data_source_service)]


def get_personal_memory_service(session: DbSession) -> PersonalMemoryService:
    return PersonalMemoryService(
        SqlAlchemyPersonalMemoryRepository(session),
        KnowledgeContentGuard(),
        SqlAlchemyAuditSink(session),
        lambda: new_id("mem"),
    )


PersonalMemoryServiceDep = Annotated[PersonalMemoryService, Depends(get_personal_memory_service)]


def get_knowledge_service(request: Request, session: DbSession) -> KnowledgeGovernanceService:
    return KnowledgeGovernanceService(
        SqlAlchemyKnowledgeRepository(session),
        cast(KnowledgeIndexPort, request.app.state.knowledge_index),
        KnowledgeContentGuard(),
        SqlAlchemyAuditSink(session),
        lambda: new_id("candidate"),
    )


KnowledgeServiceDep = Annotated[KnowledgeGovernanceService, Depends(get_knowledge_service)]


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    identity_service: IdentityServiceDep,
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationFailed("bearer token is required")
    return identity_service.resolve_principal(credentials.credentials)


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


def require_roles(
    *roles: Role,
) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    """Create a dependency that accepts any listed role; ADMIN grants all roles."""

    accepted = frozenset(roles)
    if not accepted:
        raise ValueError("at least one role is required")

    def dependency(principal: CurrentPrincipal) -> AuthenticatedPrincipal:
        if not any(principal.has_role(role) for role in accepted):
            raise Forbidden("the current role cannot perform this operation")
        return principal

    return dependency


def build_identity_service(
    session: Session,
    *,
    token_service: HMACTokenService,
    password_hasher: PasswordHasher,
) -> IdentityService:
    """Non-request helper used by startup bootstrapping and tests."""

    return IdentityService(SqlAlchemyUserRepository(session), password_hasher, token_service)
