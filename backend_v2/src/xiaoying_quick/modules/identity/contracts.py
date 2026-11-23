"""Public identity contracts."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime

from xiaoying_quick.shared.compat import StrEnum


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"
    DATA_SOURCE_ADMIN = "data_source_admin"
    KNOWLEDGE_REVIEWER = "knowledge_reviewer"

    def grants(self, required: Role) -> bool:
        return self is Role.ADMIN or self is required


class DataScopeMode(StrEnum):
    DENY = "deny"
    RESTRICTED = "restricted"
    ALL = "all"


@dataclass(frozen=True)
class DataAccessScope:
    """Versioned ABAC scope loaded from trusted identity persistence."""

    mode: DataScopeMode
    organizations: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("data scope version must be positive")
        organizations = _scope_values(self.organizations, "organization")
        regions = _scope_values(self.regions, "region")
        if self.mode is DataScopeMode.RESTRICTED:
            if not organizations or not regions:
                raise ValueError("restricted data scope requires organization and region values")
        elif organizations or regions:
            raise ValueError("deny/all data scope cannot carry organization or region values")
        object.__setattr__(self, "organizations", organizations)
        object.__setattr__(self, "regions", regions)

    @classmethod
    def deny(cls, *, version: int = 1) -> DataAccessScope:
        return cls(mode=DataScopeMode.DENY, version=version)

    @classmethod
    def full_access(cls, *, version: int = 1) -> DataAccessScope:
        return cls(mode=DataScopeMode.ALL, version=version)

    @classmethod
    def restricted(
        cls,
        *,
        organizations: tuple[str, ...],
        regions: tuple[str, ...],
        version: int = 1,
    ) -> DataAccessScope:
        return cls(
            mode=DataScopeMode.RESTRICTED,
            organizations=organizations,
            regions=regions,
            version=version,
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "mode": self.mode.value,
            "organizations": self.organizations,
            "regions": self.regions,
            "version": self.version,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def at_version(self, version: int) -> DataAccessScope:
        return replace(self, version=version)


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    username_key: str
    display_name: str
    password_digest: str
    role: Role
    is_active: bool
    created_at: datetime
    data_scope: DataAccessScope = field(default_factory=DataAccessScope.deny, repr=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str
    username: str
    display_name: str
    role: Role
    data_scope: DataAccessScope = field(default_factory=DataAccessScope.deny, repr=False)

    def has_role(self, required: Role) -> bool:
        return self.role.grants(required)


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    username: str
    role: Role
    issued_at: datetime
    expires_at: datetime | None
    token_id: str


def _scope_values(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) > 128:
        raise ValueError(f"data scope {label} values exceed the limit")
    normalized: list[str] = []
    for value in values:
        clean = unicodedata.normalize("NFKC", value).strip()
        if not 1 <= len(clean) <= 128:
            raise ValueError(f"data scope {label} value is invalid")
        if any(unicodedata.category(character).startswith("C") for character in clean):
            raise ValueError(f"data scope {label} value is invalid")
        normalized.append(clean)
    return tuple(sorted(set(normalized)))
