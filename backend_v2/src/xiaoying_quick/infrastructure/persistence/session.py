"""SQLAlchemy engine and unit-of-work session construction."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

SessionFactory = sessionmaker[Session]


def build_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> Engine:
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "echo": echo,
    }
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    elif database_url.startswith("mysql"):
        options["pool_recycle"] = 3600
        options["connect_args"] = {"charset": "utf8mb4", "connect_timeout": 10}
        if pool_size is not None:
            options["pool_size"] = pool_size
        if max_overflow is not None:
            options["max_overflow"] = max_overflow
    return configure_engine(create_engine(database_url, **options))


def configure_engine(engine: Engine) -> Engine:
    """Disable features AnalyticDB MySQL does not implement, such as SAVEPOINT."""

    host = (engine.url.host or "").lower()
    if "ads.aliyuncs.com" in host or "analyticdb" in host:
        engine.dialect.supports_savepoints = False
    return engine


def build_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: SessionFactory) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def optional_nested_transaction(session: Session) -> Iterator[None]:
    """Use SAVEPOINT when the dialect supports it; otherwise stay in the outer unit of work."""

    bind = session.get_bind()
    supports = True if bind is None else bool(getattr(bind.dialect, "supports_savepoints", True))
    if supports:
        with session.begin_nested():
            yield
        return
    yield
