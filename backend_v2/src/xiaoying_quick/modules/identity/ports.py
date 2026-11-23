"""Ports owned by the identity module."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from xiaoying_quick.modules.identity.contracts import DataAccessScope, UserRecord


class UserRepository(Protocol):
    def count(self) -> int: ...

    def get_by_id(self, user_id: str) -> UserRecord | None: ...

    def get_by_username_key(self, username_key: str) -> UserRecord | None: ...

    def list_all(self) -> tuple[UserRecord, ...]: ...

    def add(self, user: UserRecord) -> UserRecord: ...

    def set_data_scope(
        self,
        user_id: str,
        scope: DataAccessScope,
        *,
        updated_by: str,
        updated_at: datetime,
    ) -> UserRecord | None: ...

    def current_scope_fingerprint(self, user_id: str) -> str | None: ...


class IdentityAuditSink(Protocol):
    def record(
        self,
        *,
        actor_id: str,
        action: str,
        resource_id: str,
        metadata: dict[str, object],
    ) -> None: ...
