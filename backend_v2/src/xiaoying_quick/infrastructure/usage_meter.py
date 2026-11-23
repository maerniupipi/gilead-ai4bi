"""SQLAlchemy persistence adapter for the framework-independent usage meter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.usage import UsageEventModel


class SqlAlchemyUsageSink:
    def __init__(self, factory: Callable[[], Session]) -> None:
        self.factory = factory

    def __call__(self, event: Mapping[str, Any]) -> None:
        session = self.factory()
        try:
            from .monthly_quota import call_started
            started = call_started()
            session.add(UsageEventModel(**dict(event), **({"created_at":started} if started else {})))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
