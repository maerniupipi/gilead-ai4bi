"""FastAPI application factory for the new Quick backend."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from xiaoying_quick import __version__
from xiaoying_quick.api.dependencies import build_identity_service
from xiaoying_quick.api.routers import (
    agent_configs,
    audit,
    auth,
    branding,
    chatbots,
    workspace,
    chat,
    data_sources,
    eval_workbook,
    exports,
    feedback,
    knowledge,
    lab_connection,
    memory,
    model_configs,
    runs,
    skill_packs,
    system,
    usage,
)
from xiaoying_quick.bootstrap.job_runtime import start_job_runtime, stop_job_runtime
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.health import SqlAlchemyDependencyProbe
from xiaoying_quick.infrastructure.usage_meter import SqlAlchemyUsageSink
from xiaoying_quick.infrastructure.chatbots import ChatbotStore
from xiaoying_quick.infrastructure.persistence.migration_state import (
    assert_database_at_head,
)
from xiaoying_quick.infrastructure.persistence.models import (  # noqa: F401
    AgentConfigModel,
    AuditEventModel,
    DataSourceModel,
    DataSourceRevisionModel,
    DomainBindingModel,
    AnswerFeedbackModel,
    EvalBatchModel,
    EvalResultModel,
    IdentityDataScopeModel,
    IdentityUserModel,
    KnowledgeCandidateModel,
    KnowledgeEntryModel,
    PersonalMemoryModel,
    PersonalMemoryRevisionModel,
    QuickJobModel,
    RunEventModel,
    RunModel,
    SchemaSnapshotModel,
    SkillPackModel,
    UsageEventModel,
    WorkspaceBrandingModel,
)
from xiaoying_quick.infrastructure.persistence.provision import (
    apply_schema,
    ensure_database,
)
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.knowledge import (
    InMemoryKnowledgeIndex,
    SqlAlchemyKnowledgeRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
    SqlAlchemyModelConfigRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    SessionFactory,
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.search.knowledge_seed import (
    seed_published_knowledge,
)
from xiaoying_quick.infrastructure.secrets.fernet_store import LocalFernetSecretStore
from xiaoying_quick.infrastructure.source_db.sqlalchemy_adapter import (
    SqlAlchemyConnectionProbe,
)
from xiaoying_quick.modules.data_sources.ports import ConnectionProbe, SecretStore
from xiaoying_quick.modules.health import ReadinessService
from xiaoying_quick.modules.identity.contracts import DataAccessScope, Role
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.modules.knowledge.ports import KnowledgeIndexPort
from xiaoying_quick.modules.labs.ports import LabPort
from xiaoying_quick.modules.models import ModelConfigService
from xiaoying_quick.modules.usage import configure_usage_meter
from xiaoying_quick.shared.errors import (
    ApplicationError,
    AuthenticationFailed,
    Conflict,
    Forbidden,
    NotFound,
    ValidationFailed,
)
from xiaoying_quick.shared.ids import new_id

_LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    engine: Engine | None = None,
    session_factory: SessionFactory | None = None,
    secret_store: SecretStore | None = None,
    connection_probe: ConnectionProbe | None = None,
    knowledge_index: KnowledgeIndexPort | None = None,
    lab_port: LabPort | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    runtime_engine = engine or build_engine(
        runtime_settings.database_url,
        echo=runtime_settings.database_echo,
        pool_size=runtime_settings.database_pool_size,
        max_overflow=runtime_settings.database_max_overflow,
    )
    runtime_session_factory = session_factory or build_session_factory(runtime_engine)
    password_hasher = PasswordHasher()
    token_service = HMACTokenService(
        secret=runtime_settings.auth_hmac_secret.get_secret_value(),
        issuer=runtime_settings.auth_issuer,
        ttl_seconds=runtime_settings.auth_token_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        job_runtime_started = False
        try:
            if runtime_settings.db_auto_create:
                try:
                    ensure_database(runtime_settings.database_url)
                except OperationalError:
                    # A missing CREATE privilege must not block startup; table
                    # creation below still runs against the configured schema.
                    pass
                apply_schema(runtime_engine, runtime_settings.database_url)
            else:
                assert_database_at_head(runtime_engine)
            _bootstrap_admin(
                runtime_settings,
                runtime_session_factory,
                token_service=token_service,
                password_hasher=password_hasher,
            )
            _seed_and_warm_knowledge(
                runtime_session_factory,
                app.state.knowledge_index,
                runtime_settings.knowledge_root,
            )
            try:
                _seed_env_model(
                    runtime_settings,
                    runtime_session_factory,
                    app.state.secret_store,
                )
            except Exception:
                _LOGGER.warning("env model seed failed", exc_info=True)
            ChatbotStore(
                runtime_settings.secret_store_path.parent / "chatbots.sqlite3",
                mode=runtime_settings.chatbot_mode,
                database_url=runtime_settings.database_url,
            ).recover_workbook_uploads()
            await start_job_runtime(app)
            job_runtime_started = True
            yield
        finally:
            if job_runtime_started:
                await stop_job_runtime(app)
            runtime_engine.dispose()

    app = FastAPI(
        title="Xiaoying Quick API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.engine = runtime_engine
    app.state.session_factory = runtime_session_factory
    app.state.password_hasher = password_hasher
    app.state.token_service = token_service
    app.state.secret_store = secret_store
    app.state.secret_store_lock = threading.Lock()
    app.state.connection_probe = connection_probe or SqlAlchemyConnectionProbe()
    app.state.knowledge_index = knowledge_index or InMemoryKnowledgeIndex()
    app.state.lab_port = lab_port
    app.state.readiness_service = ReadinessService(
        SqlAlchemyDependencyProbe(
            runtime_engine,
            migration_managed=not runtime_settings.db_auto_create,
            lab_configured=lab_port is not None or runtime_settings.lab_endpoint_url is not None,
        )
    )
    from xiaoying_quick.infrastructure.monthly_quota import configure as configure_quota
    configure_quota(runtime_session_factory)
    configure_usage_meter(SqlAlchemyUsageSink(runtime_session_factory))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.exception_handler(ApplicationError)
    async def handle_application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        response_status = _status_for_error(exc)
        headers = {"WWW-Authenticate": "Bearer"} if response_status == 401 else None
        return JSONResponse(
            status_code=response_status,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=headers,
        )

    app.include_router(system.router)
    app.include_router(system.provision_router)
    app.include_router(auth.router)
    app.include_router(branding.public_router)
    app.include_router(branding.admin_router)
    app.include_router(chatbots.router)
    app.include_router(workspace.router)
    app.include_router(exports.router)
    app.include_router(runs.router)
    app.include_router(chat.router)
    app.include_router(eval_workbook.router)
    app.include_router(data_sources.router)
    app.include_router(model_configs.router)
    app.include_router(lab_connection.router)
    app.include_router(agent_configs.router)
    app.include_router(skill_packs.admin_router)
    app.include_router(skill_packs.public_router)
    app.include_router(knowledge.router)
    app.include_router(audit.router)
    app.include_router(usage.router)
    app.include_router(usage.personal_router)
    app.include_router(feedback.router)
    _attach_eval_page(app, runtime_settings)
    _attach_frontend(app, runtime_settings)
    return app


def _attach_eval_page(app: FastAPI, settings: Settings) -> None:
    del settings

    @app.get("/eval", include_in_schema=False)
    @app.get("/eval.html", include_in_schema=False)
    def eval_page() -> RedirectResponse:
        return RedirectResponse(url="/#/eval", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


def resolve_static_root(settings: Settings) -> Path | None:
    if settings.static_root is not None:
        return settings.static_root if (settings.static_root / "index.html").is_file() else None
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / "www", Path("www"), Path("app/www")):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _attach_frontend(app: FastAPI, settings: Settings) -> None:
    root = resolve_static_root(settings)
    if root is None:
        return
    root = root.resolve()
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")
    index = root / "index.html"

    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}")
    def frontend_spa(full_path: str) -> FileResponse:
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


def _bootstrap_admin(
    settings: Settings,
    session_factory: SessionFactory,
    *,
    token_service: HMACTokenService,
    password_hasher: PasswordHasher,
) -> None:
    username = settings.bootstrap_admin_username
    secret = settings.bootstrap_admin_password
    if not username or secret is None:
        return
    with session_scope(session_factory) as session:
        repository = SqlAlchemyUserRepository(session)
        if repository.count() > 0:
            return
        service = build_identity_service(
            session, token_service=token_service, password_hasher=password_hasher
        )
        service.create_user(
            username=username,
            password=secret.get_secret_value(),
            display_name=username,
            role=Role.ADMIN,
            data_scope=DataAccessScope.full_access(),
        )


def _status_for_error(exc: ApplicationError) -> int:
    if isinstance(exc, AuthenticationFailed):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, Forbidden):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, NotFound):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, Conflict):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, ValidationFailed):
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _seed_env_model(
    settings: Settings,
    session_factory: SessionFactory,
    secret_store: SecretStore | None,
) -> None:
    """Insert the process model settings when the registry is empty.

    SAE/UAT often have ``XIAOYING_MODEL_*`` but no rows in ``model_configs``
    until the AgentLoop dump is imported. The picker would otherwise be blank.
    """

    if not settings.model_endpoint_url or settings.model_api_key is None:
        return
    store = secret_store or LocalFernetSecretStore(
        store_path=settings.secret_store_path,
        key_path=settings.secret_key_path,
        key_from_env=settings.master_key.get_secret_value() if settings.master_key else None,
    )
    with session_scope(session_factory) as session:
        service = ModelConfigService(
            SqlAlchemyModelConfigRepository(session),
            store,
            id_factory=lambda: new_id("model"),
        )
        if service.list_configs():
            return
        service.create(
            name=settings.model_id.strip() or "默认模型",
            endpoint_url=settings.model_endpoint_url,
            model_id=settings.model_id,
            api_key=settings.model_api_key.get_secret_value(),
            temperature=settings.model_temperature,
            max_tokens=settings.model_max_tokens,
            reasoning=str(settings.model_reasoning),
            timeout_seconds=min(float(settings.model_timeout_seconds), 300.0),
            activate=True,
        )


def _seed_and_warm_knowledge(
    session_factory: SessionFactory,
    index: KnowledgeIndexPort,
    knowledge_root: Path,
) -> None:
    with session_scope(session_factory) as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        imported = seed_published_knowledge(repository, knowledge_root)
        published = repository.list_published()
        index.rebuild(published)
        _LOGGER.info(
            "knowledge ready: seeded %s sections, %s published (root=%s)",
            imported,
            len(published),
            knowledge_root,
        )


app = create_app()
