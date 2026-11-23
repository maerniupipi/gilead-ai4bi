from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from xiaoying_quick.shared.compat import StrEnum


class KnowledgeScope(StrEnum):
    PERSONAL = "personal"
    BUSINESS = "business"
    DOMAIN = "domain"


class KnowledgeState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    PENDING_REVIEW = "pending_review"
    APPROVED_PENDING_PUBLISH = "approved_pending_publish"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class PersonalMemoryEntry:
    id: str
    owner_id: str
    category: str
    content: str
    source_run_id: str | None
    state: KnowledgeState
    created_at: datetime
    revoked_at: datetime | None = None
    version: int = 1


@dataclass(frozen=True)
class PersonalMemoryRevision:
    id: str
    memory_id: str
    version: int
    category: str
    content: str
    source_run_id: str | None
    state: KnowledgeState
    created_at: datetime

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("personal memory revision must be positive")


@dataclass(frozen=True)
class KnowledgeCandidate:
    id: str
    scope: KnowledgeScope
    domain_id: str | None
    title: str
    content: str
    rationale: str
    evidence_refs: tuple[str, ...]
    source_run_id: str | None
    source_user_id: str
    state: KnowledgeState
    created_at: datetime
    source_question: str | None = None
    clarification_question: str | None = None
    clarification_answer: str | None = None
    applicability: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None

    def __post_init__(self) -> None:
        validate_validity_window(self.valid_from, self.valid_until)

    @property
    def logical_key(self) -> str:
        return knowledge_logical_key(self.scope, self.domain_id, self.title)


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    scope: KnowledgeScope
    domain_id: str | None
    title: str
    content: str
    version: int
    content_hash: str
    source_candidate_id: str | None
    state: KnowledgeState
    published_by: str
    published_at: datetime
    applicability: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        validate_validity_window(self.valid_from, self.valid_until)

    @property
    def logical_key(self) -> str:
        return knowledge_logical_key(self.scope, self.domain_id, self.title)

    def is_valid_at(self, instant: datetime | None = None) -> bool:
        return knowledge_is_valid_at(
            self.valid_from,
            self.valid_until,
            instant=instant,
        )


@dataclass(frozen=True)
class KnowledgeSnapshot:
    version: int
    entries: tuple[KnowledgeEntry, ...]
    created_at: datetime


@dataclass(frozen=True)
class MemoryWriteRequest:
    category: str
    content: str
    source_run_id: str | None = None


@dataclass(frozen=True)
class MemoryUpdateRequest:
    category: str
    content: str
    source_run_id: str | None = None


@dataclass(frozen=True)
class CandidateRequest:
    scope: KnowledgeScope
    title: str
    content: str
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    domain_id: str | None = None
    source_run_id: str | None = None
    source_question: str | None = None
    clarification_question: str | None = None
    clarification_answer: str | None = None
    applicability: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        validate_validity_window(self.valid_from, self.valid_until)


def validate_validity_window(
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> None:
    if valid_from is None or valid_until is None:
        return
    if _utc_comparable(valid_until) <= _utc_comparable(valid_from):
        raise ValueError("valid_until must be later than valid_from")


def knowledge_is_valid_at(
    valid_from: datetime | None,
    valid_until: datetime | None,
    *,
    instant: datetime | None = None,
) -> bool:
    current = _utc_comparable(instant or datetime.now(timezone.utc))
    starts = _utc_comparable(valid_from) if valid_from is not None else None
    ends = _utc_comparable(valid_until) if valid_until is not None else None
    return (starts is None or starts <= current) and (ends is None or current < ends)


def _utc_comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_knowledge_title(title: str) -> str:
    """Return the stable comparison form used by every knowledge adapter."""

    normalized = unicodedata.normalize("NFKC", title)
    return " ".join(normalized.split()).casefold()


def knowledge_logical_key(
    scope: KnowledgeScope,
    domain_id: str | None,
    title: str,
) -> str:
    """Identify one version chain without requiring a migration of legacy rows."""

    normalized_domain = unicodedata.normalize("NFKC", domain_id or "").strip().casefold()
    canonical = json.dumps(
        [scope.value, normalized_domain, normalize_knowledge_title(title)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
