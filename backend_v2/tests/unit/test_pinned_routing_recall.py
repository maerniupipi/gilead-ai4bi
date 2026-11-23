"""The routing rulebook is resident, whole, and only where it is needed.

Routing is not a retrieval problem. §2's priority table and §3's closed keyword
lists decide where *any* question goes, so ranking them by word overlap against
the question is backwards: "今年京东上安达唐的销量是多少" shares no bigram with
the row that makes 京东 an external channel, and under a 2000-token budget that
one decisive rule was exactly the one that lost its slot.

So those sections are pinned — at full length, at the top of the order, and at
L0 only. L1 is shared by planning and answering, which have already had the
domain decided for them; handing them a rulebook would spend their budget on a
question nobody is asking them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.repositories.knowledge import (
    SqlAlchemyKnowledgeRepository,
)
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.infrastructure.search import SqlAlchemyKnowledgeRecallSource
from xiaoying_quick.infrastructure.search.knowledge_seed import (
    is_pinned,
    seed_published_knowledge,
)
from xiaoying_quick.modules.context import (
    ContextBroker,
    MatchMethod,
    RecallDecision,
    RecallHit,
    RecallLevel,
    RecallPolicy,
    RecallRequest,
    RecallSourceType,
)
from xiaoying_quick.shared.ids import new_id

_QUESTION = "今年京东上安达唐的销量是多少？"

# A stand-in for the real index, shaped the way the pin reads it: numbered ##
# headings under the filename the seed map keys on. Written here rather than
# read from ../knowledge so the test measures the mechanism and not today's
# copy of the document.
_INDEX = """\
# 实验室总索引

## 0. 文档分工
本文只讲路由。口径定义在《业务知识》。

## 1. 路由表
| 域 | 典型信号 |
|---|---|
| actual | 开票、达成 |
| ext_simple | 份额、市场规模 |

## 2. 判别流程（按序）
### 2.1 先分内外
1. 含「内外部」→ 外部。
5. 皆无 → 内部。

## 3. 关键词与 KPI 词表（路由用）
### 3.1 外部维度（命中 → 外部）
| 渠道 | 自营、POP、电商、京东、阿里、天猫 |

## 4. 易混案例
| 安达唐的达成是多少 | `actual` |

## 5. 路由纠正记录
| 自营渠道今年可定卖了多少 | `ext_simple` |
"""


def _knowledge_root(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge" / "项目知识文档"
    root.mkdir(parents=True)
    (root / "实验室总索引.md").write_text(_INDEX, encoding="utf-8")
    return tmp_path / "knowledge"


def _packs(knowledge_root: Path):  # type: ignore[no-untyped-def]
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        seed_published_knowledge(SqlAlchemyKnowledgeRepository(session), knowledge_root)
    with session_scope(factory) as session:
        broker = ContextBroker(
            source=SqlAlchemyKnowledgeRecallSource(session),
            policy=RecallPolicy.quick_default(),
        )
        now = datetime.now(timezone.utc)
        resident = broker.recall(
            RecallRequest(
                request_id=new_id("recall"),
                level=RecallLevel.L0_RESIDENT,
                actor_id="user-1",
                session_id="sess-1",
                topic_id="topic-1",
            ),
            performed_at=now,
        )
        understanding = broker.recall(
            RecallRequest(
                request_id=new_id("recall"),
                level=RecallLevel.L1_UNDERSTANDING,
                actor_id="user-1",
                session_id="sess-1",
                frame_id="frame-1",
                topic_id="topic-1",
                query=_QUESTION,
            ),
            performed_at=now,
        )
    return resident, understanding


def test_the_rulebook_reaches_l0_whole(tmp_path: Path) -> None:
    resident, _ = _packs(_knowledge_root(tmp_path))

    pinned = [hit for hit in resident.items if hit.resident_verbatim]

    assert [hit.section_id for hit in pinned], "routing rulebook missing from L0"
    assert all(is_pinned(hit.section_id) for hit in pinned)
    # Whole, not summarised: half a priority ladder still reads like the whole
    # ladder, which is worse than not having it.
    assert all(not hit.is_summary for hit in pinned)
    # §3.1's channel row is the one the eval caught the model misquoting, and
    # it shares no wording with the question that needs it.
    joined = "\n".join(hit.content for hit in pinned)
    assert "自营" in joined and "京东" in joined
    # §0 is about how the documents divide the work; it is not a routing rule.
    assert not any("0. 文档分工" in hit.section_id for hit in pinned)


def test_planning_and_answering_do_not_pay_for_it(tmp_path: Path) -> None:
    _, understanding = _packs(_knowledge_root(tmp_path))

    assert not [hit for hit in understanding.items if hit.resident_verbatim]


def _hit(*, summary: bool, verbatim: bool) -> RecallHit:
    return RecallHit(
        source_type=RecallSourceType.BUSINESS_KNOWLEDGE,
        content_id="doc-1",
        section_id="实验室总索引.md · 2. 判别流程",
        version="1",
        content="正文",
        score=1.0,
        match_method=MatchMethod.RESIDENT,
        matched_reason="常驻路由规则",
        token_count=2,
        is_summary=summary,
        resident_verbatim=verbatim,
    )


def _authorize(hit: RecallHit) -> RecallDecision:
    policy = RecallPolicy.quick_default()
    return policy.authorize(
        RecallRequest(
            request_id=new_id("recall"),
            level=RecallLevel.L0_RESIDENT,
            actor_id="user-1",
            session_id="sess-1",
            topic_id="topic-1",
        ),
        hit,
        policy.for_level(RecallLevel.L0_RESIDENT),
    )


def test_full_text_at_l0_is_refused_unless_it_is_pinned() -> None:
    """The summaries-only rule is what keeps a catalogue a catalogue.

    The pin is the one exception, and it is spelled as an exception rather than
    as a hole: anything else arriving whole at L0 is still turned away.
    """

    assert _authorize(_hit(summary=False, verbatim=False)) is RecallDecision.DENIED_NOT_SUMMARY
    assert _authorize(_hit(summary=False, verbatim=True)) is RecallDecision.SELECTED
