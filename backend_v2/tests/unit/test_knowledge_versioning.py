from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from xiaoying_quick.infrastructure.persistence.models.knowledge import KnowledgeEntryModel
from xiaoying_quick.infrastructure.persistence.repositories.knowledge import (
    current_published_rows,
)
from xiaoying_quick.modules.knowledge.content_guard import KnowledgeContentGuard
from xiaoying_quick.modules.knowledge.contracts import (
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeState,
    ReviewDecision,
    knowledge_logical_key,
)
from xiaoying_quick.modules.knowledge.service import KnowledgeGovernanceService

_NOW = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)


def _candidate() -> KnowledgeCandidate:
    return KnowledgeCandidate(
        id="candidate-1",
        scope=KnowledgeScope.DOMAIN,
        domain_id="ACTUAL",
        title="ＡＣＴＵＡＬ   路由",
        content="Actual 域路由口径 v2",
        rationale="口径修订",
        evidence_refs=("review-1",),
        source_run_id=None,
        source_user_id="author-1",
        state=KnowledgeState.PENDING_REVIEW,
        created_at=_NOW,
    )


def _entry(*, version: int = 2) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=f"knowledge-{version}",
        scope=KnowledgeScope.DOMAIN,
        domain_id="actual",
        title="actual 路由",
        content=f"Actual 域路由口径 v{version}",
        version=version,
        content_hash=f"hash-{version}",
        source_candidate_id="candidate-1",
        state=KnowledgeState.PUBLISHED,
        published_by="reviewer-1",
        published_at=_NOW,
    )


def test_logical_key_normalizes_scope_domain_unicode_case_and_whitespace() -> None:
    candidate = _candidate()
    entry = _entry()

    assert candidate.logical_key == entry.logical_key
    assert candidate.logical_key == knowledge_logical_key(
        KnowledgeScope.DOMAIN,
        " actual ",
        "actual 路由",
    )
    assert candidate.logical_key != knowledge_logical_key(
        KnowledgeScope.BUSINESS,
        "actual",
        "actual 路由",
    )


def test_knowledge_validity_window_is_ordered_and_end_is_exclusive() -> None:
    with pytest.raises(ValueError, match="valid_until must be later"):
        replace(
            _candidate(),
            valid_from=_NOW,
            valid_until=_NOW,
        )

    entry = replace(
        _entry(),
        valid_from=_NOW - timedelta(hours=1),
        valid_until=_NOW + timedelta(hours=1),
    )

    assert entry.is_valid_at(_NOW)
    assert entry.is_valid_at(_NOW - timedelta(hours=1))
    assert not entry.is_valid_at(_NOW - timedelta(hours=1, seconds=1))
    assert not entry.is_valid_at(_NOW + timedelta(hours=1))


def test_repository_compatibility_filter_collapses_legacy_duplicate_publications() -> None:
    older = KnowledgeEntryModel(
        id="legacy-v1",
        scope="domain",
        domain_id="ACTUAL",
        title="ＡＣＴＵＡＬ   路由",
        content="v1",
        version=1,
        content_hash="hash-v1",
        source_candidate_id=None,
        state="published",
        published_by="legacy",
        published_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )
    current = KnowledgeEntryModel(
        id="legacy-v2",
        scope="domain",
        domain_id="actual",
        title="actual 路由",
        content="v2",
        version=2,
        content_hash="hash-v2",
        source_candidate_id=None,
        state="published",
        published_by="legacy",
        published_at=_NOW,
    )
    archived = KnowledgeEntryModel(
        id="legacy-v3-archived",
        scope="domain",
        domain_id="actual",
        title="actual 路由",
        content="v3 draft",
        version=3,
        content_hash="hash-v3",
        source_candidate_id=None,
        state="superseded",
        published_by="legacy",
        published_at=_NOW,
    )

    assert [row.id for row in current_published_rows((older, current, archived))] == ["legacy-v2"]


class _Repository:
    def __init__(self) -> None:
        self.candidate = _candidate()
        self.published = _entry()

    def get_candidate(self, candidate_id: str) -> KnowledgeCandidate | None:
        return self.candidate if candidate_id == self.candidate.id else None

    def mark_reviewed(
        self,
        candidate_id: str,
        state: KnowledgeState,
        reviewer_id: str,
        comment: str | None,
        edited_content: str | None = None,
    ) -> KnowledgeCandidate:
        del candidate_id, reviewer_id, comment
        return replace(
            self.candidate,
            state=state,
            content=edited_content or self.candidate.content,
        )

    def publish(self, candidate: KnowledgeCandidate, publisher_id: str) -> KnowledgeEntry:
        assert candidate.state is KnowledgeState.APPROVED_PENDING_PUBLISH
        assert publisher_id == "reviewer-1"
        return self.published

    def list_published(
        self,
        *,
        scope: KnowledgeScope | None = None,
        domain_id: str | None = None,
    ) -> list[KnowledgeEntry]:
        del scope, domain_id
        return [self.published]


class _Index:
    def __init__(self) -> None:
        self.entries: list[KnowledgeEntry] = []

    def rebuild(self, published_entries: list[KnowledgeEntry]) -> int:
        self.entries = published_entries
        return len(self.entries)


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(
        self,
        *,
        actor_id: str,
        action: str,
        resource_id: str,
        metadata: dict[str, object],
    ) -> None:
        del actor_id
        self.events.append((action, resource_id, metadata))


def test_governance_service_rebuilds_index_with_current_version_and_audits_it() -> None:
    repository = _Repository()
    index = _Index()
    audit = _Audit()
    service = KnowledgeGovernanceService(
        repository,  # type: ignore[arg-type]
        index,
        KnowledgeContentGuard(),
        audit,
        lambda: "unused",
    )

    published = service.review(
        candidate_id="candidate-1",
        reviewer_id="reviewer-1",
        decision=ReviewDecision.APPROVE,
        comment="已核验",
    )

    assert published == repository.published
    assert index.entries == [repository.published]
    assert audit.events == [
        (
            "knowledge_entry.published",
            repository.published.id,
            {"candidate_id": "candidate-1", "version": 2},
        )
    ]
