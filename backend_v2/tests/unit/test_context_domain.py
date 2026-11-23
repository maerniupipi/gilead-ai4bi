from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from xiaoying_quick.modules.context import (
    ContextBroker,
    MatchMethod,
    PublicationStatus,
    RecallHit,
    RecallLevel,
    RecallPolicy,
    RecallRequest,
    RecallSourceType,
    RecallValidationError,
)


class FakeRecallSource:
    def __init__(self, hits: tuple[RecallHit, ...]) -> None:
        self.hits = hits
        self.requests: list[RecallRequest] = []

    def search(self, request: RecallRequest, *, candidate_limit: int) -> tuple[RecallHit, ...]:
        self.requests.append(request)
        return self.hits[:candidate_limit]


def _hit(
    content_id: str,
    *,
    source_type: RecallSourceType = RecallSourceType.BUSINESS_KNOWLEDGE,
    score: float = 0.8,
    owner_id: str | None = None,
    session_id: str | None = None,
    topic_id: str | None = None,
    publication_status: PublicationStatus = PublicationStatus.PUBLISHED,
    tokens: int = 40,
    is_summary: bool = True,
) -> RecallHit:
    return RecallHit(
        source_type=source_type,
        owner_id=owner_id,
        session_id=session_id,
        topic_id=topic_id,
        content_id=content_id,
        section_id="main",
        version="v1",
        content=f"content:{content_id}",
        score=score,
        match_method=MatchMethod.BM25,
        matched_reason="metric alias matched",
        token_count=tokens,
        publication_status=publication_status,
        is_summary=is_summary,
    )


def test_l1_recall_enforces_acl_publication_and_records_every_decision() -> None:
    source = FakeRecallSource(
        (
            _hit("published"),
            _hit(
                "mine",
                source_type=RecallSourceType.PERSONAL_MEMORY,
                owner_id="user-1",
                publication_status=PublicationStatus.PRIVATE,
                score=0.95,
            ),
            _hit(
                "other-user",
                source_type=RecallSourceType.PERSONAL_MEMORY,
                owner_id="user-2",
                publication_status=PublicationStatus.PRIVATE,
                score=0.99,
            ),
            _hit("pending", publication_status=PublicationStatus.PENDING_REVIEW),
        )
    )
    broker = ContextBroker(source=source, policy=RecallPolicy.quick_default())
    request = RecallRequest(
        request_id="rq-1",
        level=RecallLevel.L1_UNDERSTANDING,
        actor_id="user-1",
        session_id="session-1",
        frame_id="frame-1",
        query="销售额口径",
    )

    pack = broker.recall(request, performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))

    assert {item.content_id for item in pack.items} == {"published", "mine"}
    assert len(pack.receipt.entries) == 4
    decisions = {entry.content_id: entry.decision.value for entry in pack.receipt.entries}
    assert decisions["other-user"] == "denied_owner"
    assert decisions["pending"] == "denied_unpublished"
    assert pack.receipt.total_tokens == 80


def test_l0_rejects_full_documents_and_l3_requires_targeted_failure_context() -> None:
    source = FakeRecallSource((_hit("full", is_summary=False),))
    broker = ContextBroker(source=source, policy=RecallPolicy.quick_default())
    l0 = RecallRequest(
        request_id="rq-l0",
        level=RecallLevel.L0_RESIDENT,
        actor_id="user-1",
        session_id="session-1",
    )

    pack = broker.recall(l0, performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))
    assert pack.items == ()
    assert pack.receipt.entries[0].decision.value == "denied_not_summary"

    with pytest.raises(RecallValidationError):
        broker.recall(
            RecallRequest(
                request_id="rq-l3",
                level=RecallLevel.L3_TARGETED_RECOVERY,
                actor_id="user-1",
                session_id="session-1",
                frame_id="frame-1",
                atom_id="atom-1",
                query="unknown column",
            ),
            performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
        )


def test_session_patch_is_immediately_recallable_but_only_in_its_session() -> None:
    patch_hit = _hit(
        "patch-route",
        source_type=RecallSourceType.DOMAIN_KNOWLEDGE,
        publication_status=PublicationStatus.PRIVATE,
    )
    patch_hit = replace(
        patch_hit,
        session_id="session-1",
        topic_id="topic-1",
        from_session_patch=True,
    )
    broker = ContextBroker(
        source=FakeRecallSource((patch_hit,)), policy=RecallPolicy.quick_default()
    )
    own_request = RecallRequest(
        request_id="rq-patch-own",
        level=RecallLevel.L1_UNDERSTANDING,
        actor_id="user-1",
        session_id="session-1",
        frame_id="frame-1",
        topic_id="topic-1",
        query="销售额",
    )

    own_pack = broker.recall(
        own_request, performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
    )
    other_pack = broker.recall(
        replace(own_request, request_id="rq-patch-other", session_id="session-2"),
        performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
    )

    assert tuple(item.content_id for item in own_pack.items) == ("patch-route",)
    assert other_pack.items == ()
    assert other_pack.receipt.entries[0].decision.value == "denied_session"

    wrong_topic = broker.recall(
        replace(own_request, request_id="rq-patch-topic", topic_id="topic-2"),
        performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
    )
    assert wrong_topic.items == ()
    assert wrong_topic.receipt.entries[0].decision.value == "denied_topic"


def test_recall_budget_is_deterministic_and_written_to_receipt() -> None:
    policy = RecallPolicy.quick_default().with_budget(
        RecallLevel.L2_ATOM_DETAIL,
        max_items=2,
        max_tokens=70,
        candidate_limit=5,
    )
    hits = (
        _hit("low", score=0.2, tokens=20),
        _hit("highest", score=0.9, tokens=40),
        _hit("second", score=0.8, tokens=30),
        _hit("too-large", score=0.7, tokens=50),
    )
    broker = ContextBroker(source=FakeRecallSource(hits), policy=policy)
    request = RecallRequest(
        request_id="rq-2",
        level=RecallLevel.L2_ATOM_DETAIL,
        actor_id="user-1",
        session_id="session-1",
        frame_id="frame-1",
        atom_id="atom-1",
        domain_ids=("sales",),
        query="华东销售额",
    )

    pack = broker.recall(request, performed_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc))

    assert tuple(item.content_id for item in pack.items) == ("highest", "second")
    assert pack.receipt.total_tokens == 70
    assert any(entry.decision.value == "denied_budget" for entry in pack.receipt.entries)
