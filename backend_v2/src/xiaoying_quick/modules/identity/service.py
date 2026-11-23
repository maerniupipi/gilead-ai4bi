"""Identity use cases independent of HTTP and persistence technology."""

from __future__ import annotations

import unicodedata
from datetime import datetime

from xiaoying_quick.modules.identity.contracts import (
    AuthenticatedPrincipal,
    DataAccessScope,
    Role,
    UserRecord,
)
from xiaoying_quick.modules.identity.ports import IdentityAuditSink, UserRepository
from xiaoying_quick.modules.identity.security import HMACTokenService, PasswordHasher
from xiaoying_quick.shared.clock import Clock, SystemClock
from xiaoying_quick.shared.errors import (
    AuthenticationFailed,
    Conflict,
    Forbidden,
    NotFound,
    ValidationFailed,
)
from xiaoying_quick.shared.ids import new_id


def normalize_username(username: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", username).strip()
    if not 1 <= len(normalized) <= 64:
        raise ValidationFailed("username must contain between 1 and 64 characters")
    if any(
        character.isspace() or unicodedata.category(character).startswith("C")
        for character in normalized
    ):
        raise ValidationFailed("username cannot contain whitespace or control characters")
    return normalized, normalized.casefold()


class IdentityService:
    def __init__(
        self,
        repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: HMACTokenService,
        *,
        clock: Clock | None = None,
        audit: IdentityAuditSink | None = None,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._clock = clock or SystemClock()
        self._audit = audit

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role: Role = Role.USER,
        data_scope: DataAccessScope | None = None,
    ) -> UserRecord:
        username, username_key = normalize_username(username)
        if self._repository.get_by_username_key(username_key):
            raise Conflict("username already exists")
        clean_display_name = unicodedata.normalize("NFKC", display_name or username).strip()
        if not 1 <= len(clean_display_name) <= 128:
            raise ValidationFailed("display_name must contain between 1 and 128 characters")
        user = UserRecord(
            id=new_id("usr"),
            username=username,
            username_key=username_key,
            display_name=clean_display_name,
            password_digest=self._password_hasher.hash(password),
            role=role,
            is_active=True,
            created_at=self._clock.now(),
            data_scope=data_scope or DataAccessScope.deny(),
        )
        return self._repository.add(user)

    def bootstrap_first_admin(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
    ) -> UserRecord:
        if self._repository.count() > 0:
            raise Conflict("administrator already exists")
        return self.create_user(
            username=username,
            password=password,
            display_name=display_name,
            role=Role.ADMIN,
            data_scope=DataAccessScope.full_access(),
        )

    def get_by_username(self, username: str) -> UserRecord | None:
        _, username_key = normalize_username(username)
        return self._repository.get_by_username_key(username_key)

    def list_users(self, *, actor: AuthenticatedPrincipal) -> tuple[UserRecord, ...]:
        if actor.role is not Role.ADMIN:
            raise Forbidden("only an administrator can list users")
        return self._repository.list_all()

    def get_data_scope(
        self,
        *,
        actor: AuthenticatedPrincipal,
        user_id: str,
    ) -> DataAccessScope:
        self._require_scope_admin(actor)
        user = self._repository.get_by_id(user_id)
        if user is None:
            raise NotFound("user not found")
        return user.data_scope

    def configure_data_scope(
        self,
        *,
        actor: AuthenticatedPrincipal,
        user_id: str,
        scope: DataAccessScope,
    ) -> UserRecord:
        self._require_scope_admin(actor)
        updated = self._repository.set_data_scope(
            user_id,
            scope,
            updated_by=actor.user_id,
            updated_at=self._clock.now(),
        )
        if updated is None:
            raise NotFound("user not found")
        if self._audit is not None:
            self._audit.record(
                actor_id=actor.user_id,
                action="identity.data_scope_updated",
                resource_id=user_id,
                metadata={
                    "mode": updated.data_scope.mode.value,
                    "version": updated.data_scope.version,
                    "scope_fingerprint": updated.data_scope.fingerprint,
                },
            )
        return updated

    def authenticate(
        self, *, username: str, password: str
    ) -> tuple[str, UserRecord, datetime | None]:
        try:
            _, username_key = normalize_username(username)
        except ValidationFailed as exc:
            raise AuthenticationFailed("invalid username or password") from exc
        user = self._repository.get_by_username_key(username_key)
        if not user or not user.is_active:
            raise AuthenticationFailed("invalid username or password")
        if not self._password_hasher.verify(password, user.password_digest):
            raise AuthenticationFailed("invalid username or password")
        principal = self.principal_from_user(user)
        token, expires_at = self._token_service.issue(principal)
        return token, user, expires_at

    def resolve_principal(self, token: str) -> AuthenticatedPrincipal:
        claims = self._token_service.verify(token)
        user = self._repository.get_by_id(claims.subject)
        if not user or not user.is_active:
            raise AuthenticationFailed("account is unavailable")
        return self.principal_from_user(user)

    @staticmethod
    def principal_from_user(user: UserRecord) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            data_scope=user.data_scope,
        )

    @staticmethod
    def _require_scope_admin(actor: AuthenticatedPrincipal) -> None:
        if actor.role is not Role.ADMIN:
            raise Forbidden("only an administrator can configure data scopes")
