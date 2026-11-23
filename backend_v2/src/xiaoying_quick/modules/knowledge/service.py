from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from .content_guard import KnowledgeContentGuard, UnsafeKnowledgeContent
from .library import is_markdown
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
    ReviewDecision,
)
from .ports import (
    KnowledgeAuditSink,
    KnowledgeIndexPort,
    KnowledgeRepository,
    PersonalMemoryRepository,
)
from .recent_digest import (
    RECENT_QUESTION_LIMIT,
    digest_recent_questions,
    is_raw_recent_question,
)


class KnowledgeNotFound(LookupError):
    pass


class InvalidKnowledgeTransition(ValueError):
    pass


class PersonalMemoryService:
    def __init__(
        self,
        repository: PersonalMemoryRepository,
        guard: KnowledgeContentGuard,
        audit: KnowledgeAuditSink,
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._guard = guard
        self._audit = audit
        self._id_factory = id_factory

    def list(self, principal_id: str) -> list[PersonalMemoryEntry]:
        self._digest_recent_if_needed(principal_id, source_run_id=None)
        return self._repository.list_for_owner(principal_id)

    def write(self, principal_id: str, request: MemoryWriteRequest) -> PersonalMemoryEntry:
        safe = replace(request, content=self._guard.validate(request.content))
        entry = self._repository.create(self._id_factory(), principal_id, safe)
        self._audit.record(
            actor_id=principal_id,
            action="personal_memory.written",
            resource_id=entry.id,
            metadata={"category": entry.category},
        )
        if entry.category == "recent":
            self._digest_recent_if_needed(principal_id, source_run_id=entry.source_run_id)
        return entry

    def update(
        self,
        principal_id: str,
        entry_id: str,
        request: MemoryUpdateRequest,
    ) -> PersonalMemoryEntry:
        safe = replace(request, content=self._guard.validate(request.content))
        entry = self._repository.update(entry_id, principal_id, safe)
        self._audit.record(
            actor_id=principal_id,
            action="personal_memory.updated",
            resource_id=entry.id,
            metadata={"category": entry.category, "version": entry.version},
        )
        return entry

    def revoke(self, principal_id: str, entry_id: str) -> PersonalMemoryEntry:
        entry = self._repository.revoke(entry_id, principal_id)
        self._audit.record(
            actor_id=principal_id,
            action="personal_memory.revoked",
            resource_id=entry.id,
            metadata={"version": entry.version},
        )
        return entry

    def history(self, principal_id: str, entry_id: str) -> Sequence[PersonalMemoryRevision]:
        return self._repository.history(entry_id, principal_id)

    def _digest_recent_if_needed(self, principal_id: str, *, source_run_id: str | None) -> None:
        entries = [
            item
            for item in self._repository.list_for_owner(principal_id)
            if item.category == "recent"
        ]
        raw = [item for item in entries if is_raw_recent_question(item.content)]
        if len(raw) <= RECENT_QUESTION_LIMIT:
            return
        insights = digest_recent_questions([item.content for item in raw])
        existing_pref = {
            item.content
            for item in self._repository.list_for_owner(principal_id)
            if item.category == "preference"
        }
        for item in entries:
            try:
                self.revoke(principal_id, item.id)
            except (LookupError, ValueError):
                continue
        for content in insights:
            try:
                self._repository.create(
                    self._id_factory(),
                    principal_id,
                    self._guarded_write("recent", content, source_run_id),
                )
            except (UnsafeKnowledgeContent, ValueError):
                continue
            if content not in existing_pref:
                try:
                    self._repository.create(
                        self._id_factory(),
                        principal_id,
                        self._guarded_write("preference", content, source_run_id),
                    )
                except (UnsafeKnowledgeContent, ValueError):
                    continue

    def _guarded_write(
        self, category: str, content: str, source_run_id: str | None
    ) -> MemoryWriteRequest:
        return MemoryWriteRequest(
            category=category,
            content=self._guard.validate(content),
            source_run_id=source_run_id,
        )


class KnowledgeGovernanceService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        index: KnowledgeIndexPort,
        guard: KnowledgeContentGuard,
        audit: KnowledgeAuditSink,
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._index = index
        self._guard = guard
        self._audit = audit
        self._id_factory = id_factory

    def propose(self, principal_id: str, request: CandidateRequest) -> KnowledgeCandidate:
        if request.scope is KnowledgeScope.PERSONAL:
            raise InvalidKnowledgeTransition("个人记忆请走直写接口")
        if request.scope is KnowledgeScope.DOMAIN and not request.domain_id:
            raise InvalidKnowledgeTransition("域知识必须指定 domain_id")
        applicability = request.applicability
        if not applicability and request.scope is KnowledgeScope.DOMAIN and request.domain_id:
            applicability = f"domain:{request.domain_id.strip()}"
        safe = replace(
            request,
            title=self._guard.validate(request.title),
            content=(self._guard.validate_markdown(request.content) if is_markdown(request.title)
                     else self._guard.validate(request.content)),
            rationale=self._guard.validate(request.rationale),
            evidence_refs=tuple(self._guard.validate(value) for value in request.evidence_refs),
            source_question=self._safe_optional(request.source_question),
            clarification_question=self._safe_optional(request.clarification_question),
            clarification_answer=self._safe_optional(request.clarification_answer),
            applicability=self._safe_optional(applicability),
        )
        candidate = self._repository.create_candidate(self._id_factory(), safe, principal_id)
        self._audit.record(
            actor_id=principal_id,
            action="knowledge_candidate.proposed",
            resource_id=candidate.id,
            metadata={"scope": candidate.scope.value, "domain_id": candidate.domain_id},
        )
        return candidate

    def published_conflicts(self, candidate: KnowledgeCandidate) -> list[KnowledgeEntry]:
        return [
            entry
            for entry in self._repository.list_published(scope=candidate.scope)
            if entry.logical_key == candidate.logical_key
        ]

    def list_candidates(
        self, state: KnowledgeState | None = KnowledgeState.PENDING_REVIEW
    ) -> list[KnowledgeCandidate]:
        return self._repository.list_candidates(state)

    def review(
        self,
        *,
        candidate_id: str,
        reviewer_id: str,
        decision: ReviewDecision,
        comment: str | None = None,
        edited_content: str | None = None,
    ) -> KnowledgeCandidate | KnowledgeEntry:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise KnowledgeNotFound(candidate_id)
        if candidate.state is not KnowledgeState.PENDING_REVIEW:
            raise InvalidKnowledgeTransition("仅待审核候选可以处理")
        if decision is ReviewDecision.REJECT:
            rejected = self._repository.mark_reviewed(
                candidate_id, KnowledgeState.REJECTED, reviewer_id, comment, None
            )
            self._audit.record(
                actor_id=reviewer_id,
                action="knowledge_candidate.rejected",
                resource_id=candidate_id,
                metadata={},
            )
            return rejected
        safe_edited_content = (
            (self._guard.validate_markdown(edited_content) if is_markdown(candidate.title)
             else self._guard.validate(edited_content)) if edited_content is not None else None
        )
        approved = self._repository.mark_reviewed(
            candidate_id,
            KnowledgeState.APPROVED_PENDING_PUBLISH,
            reviewer_id,
            comment,
            safe_edited_content,
        )
        published = self._repository.publish(approved, reviewer_id)
        self._index.rebuild(self._repository.list_published())
        self._audit.record(
            actor_id=reviewer_id,
            action="knowledge_entry.published",
            resource_id=published.id,
            metadata={"candidate_id": candidate_id, "version": published.version},
        )
        return published

    def published(
        self, *, scope: KnowledgeScope | None = None, domain_id: str | None = None
    ) -> list[KnowledgeEntry]:
        return self._repository.list_published(scope=scope, domain_id=domain_id)

    def _safe_optional(self, value: str | None) -> str | None:
        return self._guard.validate(value) if value and value.strip() else None
