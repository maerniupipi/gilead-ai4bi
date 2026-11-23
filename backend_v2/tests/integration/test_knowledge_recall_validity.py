from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xiaoying_quick.infrastructure.persistence.models.knowledge import KnowledgeEntryModel
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.infrastructure.search.knowledge_recall import (
    SqlAlchemyKnowledgeRecallSource,
)
from xiaoying_quick.modules.context import RecallLevel, RecallRequest


def test_recall_selects_only_currently_effective_published_knowledge(
    app: FastAPI,
    client: TestClient,
) -> None:
    del client  # Starting the TestClient lifespan creates the test schema.
    now = datetime.now(timezone.utc)
    records = (
        ("knowledge-active", now - timedelta(days=1), now + timedelta(days=1)),
        ("knowledge-future", now + timedelta(days=1), now + timedelta(days=2)),
        ("knowledge-expired", now - timedelta(days=2), now - timedelta(days=1)),
        ("knowledge-unbounded", None, None),
    )
    with session_scope(app.state.session_factory) as session:
        for index, (entry_id, valid_from, valid_until) in enumerate(records, start=1):
            session.add(
                KnowledgeEntryModel(
                    id=entry_id,
                    scope="business",
                    domain_id=None,
                    title=f"有效期召回规则 {index}",
                    content=f"这是用于有效期召回验证的知识 {index}",
                    version=1,
                    content_hash=str(index) * 64,
                    source_candidate_id=None,
                    applicability="business:shared",
                    valid_from=valid_from,
                    valid_until=valid_until,
                    state="published",
                    published_by="test",
                    published_at=now,
                )
            )

    with session_scope(app.state.session_factory) as session:
        hits = SqlAlchemyKnowledgeRecallSource(session).search(
            RecallRequest(
                request_id="validity-recall",
                level=RecallLevel.L1_UNDERSTANDING,
                actor_id="reader",
                session_id="session-validity",
                query="有效期召回规则",
            ),
            candidate_limit=100,
        )

    selected = {hit.content_id for hit in hits if hit.content_id.startswith("knowledge-")}
    assert selected == {"knowledge-active", "knowledge-unbounded"}
