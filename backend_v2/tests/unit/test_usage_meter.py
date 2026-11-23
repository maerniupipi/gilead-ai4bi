from __future__ import annotations

from xiaoying_quick.infrastructure.usage_meter import SqlAlchemyUsageSink
from xiaoying_quick.modules.usage.meter import (
    UsageAttribution,
    bind_usage_attribution,
    configure_usage_meter,
    current_attribution,
    record_llm_usage,
)


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.closed = False

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_record_llm_usage_writes_attributed_event() -> None:
    sessions: list[_FakeSession] = []

    def factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    configure_usage_meter(SqlAlchemyUsageSink(factory))
    attr = UsageAttribution(
        user_id="u1",
        username="alice",
        display_name="Alice",
        run_id="run_1",
        session_id="sess_1",
        mode="insight",
        question="DDI表现怎么样",
    )
    with bind_usage_attribution(attr):
        assert current_attribution() is attr
        record_llm_usage(
            purpose="agent.step1",
            model_id="demo-model",
            request_id="req1",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    assert current_attribution() is None
    assert len(sessions) == 1
    session = sessions[0]
    assert session.committed is True
    assert session.closed is True
    row = session.added[0]
    assert row.user_id == "u1"
    assert row.username == "alice"
    assert row.purpose == "agent.step1"
    assert row.question == "DDI表现怎么样"
    assert row.total_tokens == 15
    assert row.mode == "insight"
    configure_usage_meter(None)


def test_record_without_attribution_is_noop() -> None:
    called = {"n": 0}

    def factory():
        called["n"] += 1
        raise AssertionError("should not open session")

    configure_usage_meter(SqlAlchemyUsageSink(factory))
    record_llm_usage(purpose="model.config_test", model_id="x", usage={"total_tokens": 1})
    assert called["n"] == 0
    configure_usage_meter(None)
