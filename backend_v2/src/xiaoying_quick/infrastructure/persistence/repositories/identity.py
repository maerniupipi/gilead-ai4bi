"""SQLAlchemy implementation of the identity repository port."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xiaoying_quick.infrastructure.persistence.models.identity import (
    IdentityDataScopeModel,
    IdentityUserModel,
)
from xiaoying_quick.infrastructure.persistence.session import optional_nested_transaction
from xiaoying_quick.modules.identity.contracts import (
    DataAccessScope,
    DataScopeMode,
    Role,
    UserRecord,
)
from xiaoying_quick.shared.errors import Conflict


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(IdentityUserModel)) or 0)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        model = self._session.get(IdentityUserModel, user_id)
        return self._to_record(model, self._scope(user_id)) if model else None

    def get_by_username_key(self, username_key: str) -> UserRecord | None:
        model = self._session.scalar(
            select(IdentityUserModel).where(IdentityUserModel.username_key == username_key)
        )
        return self._to_record(model, self._scope(model.id)) if model else None

    def list_all(self) -> tuple[UserRecord, ...]:
        users = self._session.scalars(
            select(IdentityUserModel).order_by(IdentityUserModel.created_at.desc())
        ).all()
        scopes = {
            row.user_id: row
            for row in self._session.scalars(select(IdentityDataScopeModel)).all()
        }
        return tuple(
            self._to_record(user, self._scope_from_row(scopes.get(user.id))) for user in users
        )

    def add(self, user: UserRecord) -> UserRecord:
        model = IdentityUserModel(
            id=user.id,
            username=user.username,
            username_key=user.username_key,
            display_name=user.display_name,
            password_digest=user.password_digest,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.created_at,
        )
        try:
            with optional_nested_transaction(self._session):
                self._session.add(model)
                self._session.flush()
        except IntegrityError as exc:
            raise Conflict("username already exists") from exc
        try:
            with optional_nested_transaction(self._session):
                self._session.add(
                    IdentityDataScopeModel(
                        user_id=user.id,
                        mode=user.data_scope.mode.value,
                        organizations=list(user.data_scope.organizations),
                        regions=list(user.data_scope.regions),
                        version=user.data_scope.version,
                        updated_by=None,
                        created_at=user.created_at,
                        updated_at=user.created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise Conflict("data scope already exists") from exc
        return self._to_record(model, user.data_scope)

    def set_data_scope(
        self,
        user_id: str,
        scope: DataAccessScope,
        *,
        updated_by: str,
        updated_at: datetime,
    ) -> UserRecord | None:
        user = self._session.get(IdentityUserModel, user_id)
        if user is None:
            return None
        row = self._session.get(IdentityDataScopeModel, user_id)
        next_version = (row.version if row is not None else 0) + 1
        stored = scope.at_version(next_version)
        if row is None:
            row = IdentityDataScopeModel(
                user_id=user_id,
                mode=stored.mode.value,
                organizations=list(stored.organizations),
                regions=list(stored.regions),
                version=stored.version,
                updated_by=updated_by,
                created_at=updated_at,
                updated_at=updated_at,
            )
            self._session.add(row)
        else:
            row.mode = stored.mode.value
            row.organizations = list(stored.organizations)
            row.regions = list(stored.regions)
            row.version = stored.version
            row.updated_by = updated_by
            row.updated_at = updated_at
        self._session.flush()
        return self._to_record(user, stored)

    def current_scope_fingerprint(self, user_id: str) -> str | None:
        row = self._session.execute(
            select(
                IdentityUserModel.is_active,
                IdentityDataScopeModel.mode,
                IdentityDataScopeModel.organizations,
                IdentityDataScopeModel.regions,
                IdentityDataScopeModel.version,
            )
            .outerjoin(
                IdentityDataScopeModel,
                IdentityDataScopeModel.user_id == IdentityUserModel.id,
            )
            .where(IdentityUserModel.id == user_id)
        ).one_or_none()
        if row is None or not row.is_active:
            return None
        scope = (
            DataAccessScope.deny()
            if row.mode is None
            else DataAccessScope(
                mode=DataScopeMode(row.mode),
                organizations=tuple(row.organizations),
                regions=tuple(row.regions),
                version=row.version,
            )
        )
        return scope.fingerprint

    def _scope(self, user_id: str) -> DataAccessScope:
        return self._scope_from_row(self._session.get(IdentityDataScopeModel, user_id))

    @staticmethod
    def _scope_from_row(row: IdentityDataScopeModel | None) -> DataAccessScope:
        if row is None:
            return DataAccessScope.deny()
        return DataAccessScope(
            mode=DataScopeMode(row.mode),
            organizations=tuple(row.organizations),
            regions=tuple(row.regions),
            version=row.version,
        )

    @staticmethod
    def _to_record(model: IdentityUserModel, scope: DataAccessScope) -> UserRecord:
        return UserRecord(
            id=model.id,
            username=model.username,
            username_key=model.username_key,
            display_name=model.display_name,
            password_digest=model.password_digest,
            role=Role(model.role),
            is_active=model.is_active,
            created_at=model.created_at,
            data_scope=scope,
        )
