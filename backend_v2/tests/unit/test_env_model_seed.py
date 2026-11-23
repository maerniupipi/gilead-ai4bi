from pydantic import SecretStr

from xiaoying_quick.app import _seed_env_model
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
    SqlAlchemyModelConfigRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)


def test_env_model_is_seeded_once_when_registry_empty(tmp_path) -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        db_auto_create=True,
        auth_hmac_secret=SecretStr("test-hmac-secret-with-at-least-32-bytes"),
        sql_approval_hmac_secret=SecretStr("test-sql-secret-with-at-least-32-bytes"),
        secret_store_path=tmp_path / "secrets.json",
        secret_key_path=tmp_path / "master.key",
        knowledge_root=tmp_path / "knowledge",
        model_endpoint_url="https://llm.example/v1/chat/completions",
        model_api_key=SecretStr("sk-test-key"),
        model_id="demo-model",
    )
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    try:
        _seed_env_model(settings, factory, None)
        _seed_env_model(settings, factory, None)
        with session_scope(factory) as session:
            rows = SqlAlchemyModelConfigRepository(session).list_all()
        assert len(rows) == 1
        assert rows[0].model_id == "demo-model"
        assert rows[0].is_active is True
    finally:
        engine.dispose()
