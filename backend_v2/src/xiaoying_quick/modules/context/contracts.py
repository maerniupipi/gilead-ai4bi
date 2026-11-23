"""Contracts for bounded, auditable L0-L3 context recall."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from xiaoying_quick.shared.compat import StrEnum


class RecallLevel(StrEnum):
    L0_RESIDENT = "l0_resident"
    L1_UNDERSTANDING = "l1_understanding"
    L2_ATOM_DETAIL = "l2_atom_detail"
    L3_TARGETED_RECOVERY = "l3_targeted_recovery"


class RecallSourceType(StrEnum):
    SESSION_STATE = "session_state"
    PERSONAL_MEMORY = "personal_memory"
    BUSINESS_KNOWLEDGE = "business_knowledge"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    LAB_CONSTRAINT = "lab_constraint"
    SCHEMA_CARD = "schema_card"
    SQL_POLICY = "sql_policy"
    RUNTIME_PARAMETER = "runtime_parameter"


class PublicationStatus(StrEnum):
    PRIVATE = "private"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    REVOKED = "revoked"


class MatchMethod(StrEnum):
    RESIDENT = "resident"
    STRUCTURED = "structured"
    ALIAS = "alias"
    FULL_TEXT = "full_text"
    BM25 = "bm25"
    SEMANTIC_RERANK = "semantic_rerank"
    SESSION_PATCH = "session_patch"
    TARGETED_ERROR = "targeted_error"


class RecallDecision(StrEnum):
    SELECTED = "selected"
    DENIED_SOURCE = "denied_source"
    DENIED_OWNER = "denied_owner"
    DENIED_SESSION = "denied_session"
    DENIED_TOPIC = "denied_topic"
    DENIED_UNPUBLISHED = "denied_unpublished"
    DENIED_NOT_SUMMARY = "denied_not_summary"
    DENIED_LOW_RELEVANCE = "denied_low_relevance"
    DENIED_BUDGET = "denied_budget"


@dataclass(frozen=True)
class RecallBudget:
    max_items: int
    max_tokens: int
    candidate_limit: int

    def __post_init__(self) -> None:
        if self.max_items < 1 or self.max_tokens < 1:
            raise ValueError("recall item and token budgets must be positive")
        if self.candidate_limit < self.max_items:
            raise ValueError("candidate limit cannot be smaller than max items")


@dataclass(frozen=True)
class RecallRequest:
    request_id: str
    level: RecallLevel
    actor_id: str
    session_id: str
    frame_id: str | None = None
    topic_id: str | None = None
    atom_id: str | None = None
    query: str = ""
    domain_ids: tuple[str, ...] = ()
    failure_code: str | None = None
    target_refs: tuple[str, ...] = ()
    allowed_source_types: frozenset[RecallSourceType] | None = None


@dataclass(frozen=True)
class RecallHit:
    source_type: RecallSourceType
    content_id: str
    section_id: str
    version: str
    content: str
    score: float
    match_method: MatchMethod
    matched_reason: str
    token_count: int
    owner_id: str | None = None
    session_id: str | None = None
    topic_id: str | None = None
    content_hash: str = ""
    publication_status: PublicationStatus = PublicationStatus.PUBLISHED
    rejected_reason: str | None = None
    is_summary: bool = False
    #: Resident content that is carried whole rather than shortened.
    #:
    #: L0 otherwise admits summaries only, so that a catalogue stays a
    #: catalogue. A rule table is the exception the flag exists for: half of a
    #: priority list still reads like the whole list, so shortening it is worse
    #: than dropping it. The token budget, not the shortening, is what keeps
    #: this level bounded.
    resident_verbatim: bool = False
    from_session_patch: bool = False
    acl_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.content_id.strip() or not self.section_id.strip():
            raise ValueError("recall content and section ids must not be blank")
        if not 0 <= self.score <= 1:
            raise ValueError("recall score must be between zero and one")
        if self.token_count < 0:
            raise ValueError("recall token count cannot be negative")
        if not self.content_hash:
            digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
            object.__setattr__(self, "content_hash", digest)

    def to_trace(self, *, content_limit: int = 4_000) -> dict[str, object]:
        truncated = len(self.content) > content_limit
        body = f"{self.content[:content_limit]}…" if truncated else self.content
        return {
            "content_id": self.content_id,
            "section_id": self.section_id,
            "document": self.section_id,
            "source_type": self.source_type.value,
            "match_method": self.match_method.value,
            "score": round(self.score, 3),
            "matched_reason": self.matched_reason,
            "token_count": self.token_count,
            "is_summary": self.is_summary,
            "content": body,
        }


@dataclass(frozen=True)
class RecallReceiptEntry:
    source_type: RecallSourceType
    owner_id: str | None
    topic_id: str | None
    content_id: str
    section_id: str
    version: str
    content_hash: str
    match_method: MatchMethod
    score: float
    matched_reason: str
    rejected_reason: str | None
    decision: RecallDecision
    token_count: int
    from_session_patch: bool
    is_personal: bool
    is_published_public_knowledge: bool
    acl_tags: tuple[str, ...]


@dataclass(frozen=True)
class RecallReceipt:
    receipt_id: str
    request_id: str
    level: RecallLevel
    actor_id: str
    session_id: str
    topic_id: str | None
    frame_id: str | None
    atom_id: str | None
    performed_at: datetime
    policy_version: str
    entries: tuple[RecallReceiptEntry, ...]
    total_tokens: int
    selected_count: int
    target_refs: tuple[str, ...] = ()
    failure_code: str | None = None


@dataclass(frozen=True)
class ContextPack:
    level: RecallLevel
    items: tuple[RecallHit, ...]
    receipt: RecallReceipt
