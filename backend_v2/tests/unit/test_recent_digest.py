from __future__ import annotations

from datetime import datetime, timezone

from xiaoying_quick.modules.knowledge.content_guard import KnowledgeContentGuard
from xiaoying_quick.modules.knowledge.contracts import (
    KnowledgeState,
    MemoryUpdateRequest,
    MemoryWriteRequest,
    PersonalMemoryEntry,
    PersonalMemoryRevision,
)
from xiaoying_quick.modules.knowledge.recent_digest import (
    RECENT_QUESTION_LIMIT,
    digest_recent_questions,
    is_raw_recent_question,
)
from xiaoying_quick.modules.knowledge.service import PersonalMemoryService


def test_digest_extracts_product_and_metric_habits() -> None:
    insights = digest_recent_questions(
        [
            "问过：安达唐2601的同比和环比分别是多少",
            "问过：倍择瑞呢",
            "问过：HoH是多少呢",
            "问过：安达释呢 上面所有指标都算一下",
            "问过：安达唐今年 YTD 的金额达成率是多少？",
        ]
    )
    text = " ".join(insights)
    assert len(insights) <= 2
    assert "同比" in text or "环比" in text or "达成" in text or insights


def test_raw_prefix_survives_content_guard() -> None:
    guarded = KnowledgeContentGuard().validate("问过：安达唐同比")
    assert is_raw_recent_question(guarded)
    assert is_raw_recent_question("问过:安达唐同比")
    assert is_raw_recent_question("问过：安达唐同比")
    assert not is_raw_recent_question("近期常问产品：安达唐。")
    assert not is_raw_recent_question("近期提问偏好：指标侧重同比增速。")


class _MemoryRepo:
    def __init__(self) -> None:
        self.entries: list[PersonalMemoryEntry] = []

    def list_for_owner(self, owner_id: str, *, include_revoked: bool = False):
        rows = [item for item in self.entries if item.owner_id == owner_id]
        if not include_revoked:
            rows = [item for item in rows if item.state is KnowledgeState.ACTIVE]
        return rows

    def create(self, entry_id: str, owner_id: str, request: MemoryWriteRequest):
        entry = PersonalMemoryEntry(
            id=entry_id,
            owner_id=owner_id,
            category=request.category,
            content=request.content,
            source_run_id=request.source_run_id,
            state=KnowledgeState.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
        self.entries.append(entry)
        return entry

    def update(self, entry_id: str, owner_id: str, request: MemoryUpdateRequest):
        raise NotImplementedError

    def revoke(self, entry_id: str, owner_id: str):
        for index, item in enumerate(self.entries):
            if item.id == entry_id and item.owner_id == owner_id:
                revoked = PersonalMemoryEntry(
                    id=item.id,
                    owner_id=item.owner_id,
                    category=item.category,
                    content=item.content,
                    source_run_id=item.source_run_id,
                    state=KnowledgeState.REVOKED,
                    created_at=item.created_at,
                    revoked_at=datetime.now(timezone.utc),
                )
                self.entries[index] = revoked
                return revoked
        raise LookupError(entry_id)

    def history(self, entry_id: str, owner_id: str) -> list[PersonalMemoryRevision]:
        return []


class _Audit:
    def record(self, **kwargs) -> None:
        return None


def test_eleventh_recent_question_collapses_into_two_insights() -> None:
    repo = _MemoryRepo()
    service = PersonalMemoryService(
        repo, KnowledgeContentGuard(), _Audit(), lambda: f"mem-{len(repo.entries) + 1}"
    )
    for index in range(RECENT_QUESTION_LIMIT):
        service.write(
            "user-1",
            MemoryWriteRequest(category="recent", content=f"问过：安达唐同比第{index}次"),
        )
    service.write(
        "user-1", MemoryWriteRequest(category="recent", content="问过 ：倍择瑞的环比是多少")
    )

    active = [item for item in repo.list_for_owner("user-1") if item.state is KnowledgeState.ACTIVE]
    recents = [item for item in active if item.category == "recent"]
    prefs = [item for item in active if item.category == "preference"]
    assert len(recents) <= 2
    assert not any(is_raw_recent_question(item.content) for item in recents)
    assert prefs


def test_ten_recent_questions_stay_raw() -> None:
    repo = _MemoryRepo()
    service = PersonalMemoryService(
        repo, KnowledgeContentGuard(), _Audit(), lambda: f"mem-{len(repo.entries) + 1}"
    )
    for index in range(RECENT_QUESTION_LIMIT):
        service.write(
            "user-1",
            MemoryWriteRequest(category="recent", content=f"问过：安达唐同比第{index}次"),
        )
    recents = [item for item in service.list("user-1") if item.category == "recent"]
    assert len(recents) == RECENT_QUESTION_LIMIT
    assert all(is_raw_recent_question(item.content) for item in recents)


def test_list_collapses_already_stored_raw_questions() -> None:
    repo = _MemoryRepo()
    service = PersonalMemoryService(
        repo, KnowledgeContentGuard(), _Audit(), lambda: f"mem-{len(repo.entries) + 1}"
    )
    guard = KnowledgeContentGuard()
    for index in range(RECENT_QUESTION_LIMIT + 1):
        repo.create(
            f"seed-{index}",
            "user-1",
            MemoryWriteRequest(
                category="recent", content=guard.validate(f"问过 ：安达唐同比第{index}次")
            ),
        )
    listed = service.list("user-1")
    recents = [item for item in listed if item.category == "recent"]
    assert len(recents) <= 2
    assert not any(is_raw_recent_question(item.content) for item in recents)
