"""Validate the shipped POC config and initialize only a missing lab binding."""

from pathlib import Path

from dotenv import dotenv_values

from xiaoying_quick.application.lab_connection import LabConnectionService
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence import models as _models  # noqa: F401
from xiaoying_quick.infrastructure.persistence.repositories.identity import SqlAlchemyUserRepository
from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
    SqlAlchemyModelConfigRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.secrets.fernet_store import LocalFernetSecretStore


def main() -> None:
    settings = Settings()
    values = dotenv_values(Path(".env"))
    secrets = LocalFernetSecretStore(
        store_path=settings.secret_store_path,
        key_path=settings.secret_key_path,
        key_from_env=(settings.master_key.get_secret_value() if settings.master_key else None),
    )
    engine = build_engine(settings.database_url, pool_size=1, max_overflow=0)
    try:
        with session_scope(build_session_factory(engine)) as database:
            active = SqlAlchemyModelConfigRepository(database).active()
            if active is not None:
                secrets.get(active.secret_ref)
            service = LabConnectionService(database, settings, secrets)
            api_id = values.get("JILIDE_LAB_API_ACCESS_ID")
            if not service.has_saved_config() and api_id:
                admin = SqlAlchemyUserRepository(database).get_by_username_key(
                    (settings.bootstrap_admin_username or "admin").casefold()
                )
                if admin is None:
                    raise RuntimeError("控制库没有管理员，请先完成初始化")
                service.save({
                    "active_provider": "bootcamp", "mock_enabled": False,
                    "profile": {
                        "provider": "bootcamp",
                        "endpoint_url": settings.lab_bootcamp_endpoint_url,
                        "timeout_seconds": 240,
                        "user_id": 1, "space_id": 1,
                        "labs": [{"lab_id": "actual", "api_access_id": api_id}],
                    },
                }, actor_id=admin.id)
        print("POC 控制库与模型凭证检查通过，保留现有管理配置。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
