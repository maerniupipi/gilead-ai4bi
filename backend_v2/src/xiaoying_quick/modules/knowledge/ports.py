from __future__ import annotations

from typing import Protocol

from .contracts import (
    CandidateRequest,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeState,
    MemoryUpdateRequest,
    MemoryWriteRequest,
    PersonalMemoryEntry,
    PersonalMemoryRevision,
)


class PersonalMemoryRepository(Protocol):
    def list_for_owner(
        self, owner_id: str, *, include_revoked: bool = False
    ) -> list[PersonalMemoryEntry]: ...

    def create(
        self, entry_id: str, owner_id: str, request: MemoryWriteRequest
    ) -> PersonalMemoryEntry: ...

    def update(
        self,
        entry_id: str,
        owner_id: str,
        request: MemoryUpdateRequest,
    ) -> PersonalMemoryEntry: ...

    def revoke(self, entry_id: str, owner_id: str) -> PersonalMemoryEntry: ...

    def history(self, entry_id: str, owner_id: str) -> list[PersonalMemoryRevision]: ...


class KnowledgeRepository(Protocol):
    def list_candidates(self, state: KnowledgeState | None = None) -> list[KnowledgeCandidate]: ...

    def get_candidate(self, candidate_id: str) -> KnowledgeCandidate | None: ...

    def create_candidate(
        self,
        candidate_id: str,
        request: CandidateRequest,
        source_user_id: str,
    ) -> KnowledgeCandidate: ...

    def mark_reviewed(
        self,
        candidate_id: str,
        state: KnowledgeState,
        reviewer_id: str,
        comment: str | None,
        edited_content: str | None = None,
    ) -> KnowledgeCandidate: ...

    def publish(self, candidate: KnowledgeCandidate, publisher_id: str) -> KnowledgeEntry: ...

    def list_published(
        self,
        *,
        scope: KnowledgeScope | None = None,
        domain_id: str | None = None,
    ) -> list[KnowledgeEntry]: ...

    def import_published(
        self,
        *,
        entry_id: str,
        scope: KnowledgeScope,
        domain_id: str | None,
        title: str,
        content: str,
        publisher_id: str,
    ) -> KnowledgeEntry: ...


class KnowledgeIndexPort(Protocol):
    def rebuild(self, published_entries: list[KnowledgeEntry]) -> int: ...


class KnowledgeAuditSink(Protocol):
    def record(
        self, *, actor_id: str, action: str, resource_id: str, metadata: dict[str, object]
    ) -> None: ...
