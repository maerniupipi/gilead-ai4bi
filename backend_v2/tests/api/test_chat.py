"""Quick chat and clarification HTTP boundary tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xiaoying_quick.infrastructure.llm.client import (
    AssistantTurn,
    ContentDelta,
    TurnComplete,
)
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.chat import (
    SqlAlchemyChatRepository,
    SqlAlchemyClarificationRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.jobs import SqlAlchemyJobRepository
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.session import session_scope
from xiaoying_quick.modules.clarification import (
    ClarificationCase,
    ClarificationChoice,
    ClarificationQuestion,
    ClarificationReason,
)
from xiaoying_quick.modules.identity.contracts import AuthenticatedPrincipal, UserRecord
from xiaoying_quick.modules.runs.contracts import RunStatus
from xiaoying_quick.modules.runs.service import RunService


class FakeModelClient:
    """One canned single-step answer, so the resume job completes offline."""

    async def stream_chat(self, *, purpose, messages, tools=None, max_tokens=None):
        del purpose, messages, tools, max_tokens
        yield ContentDelta(text="合成答案")
        yield TurnComplete(
            turn=AssistantTurn(
                content="合成答案",
                reasoning="",
                tool_calls=(),
                finish_reason="stop",
                usage={"total_tokens": 12},
            )
        )

    async def aclose(self) -> None:
        return None


class FakeModelRegistry:
    def active_client(self) -> FakeModelClient:
        return FakeModelClient()


def _seed_waiting_clarification(
    app: FastAPI,
    owner: UserRecord,
) -> tuple[str, str, str, int]:
    session_id = "session-waiting"
    case_id = "case-waiting"
    with session_scope(app.state.session_factory) as database:
        chats = SqlAlchemyChatRepository(database)
        chats.create_session(session_id, owner.id, "需要澄清的会话")
        principal = AuthenticatedPrincipal(
            user_id=owner.id,
            username=owner.username,
            display_name=owner.display_name,
            role=owner.role,
        )
        runs = RunService(SqlAlchemyRunRepository(database))
        run = runs.create_run(
            principal=principal,
            question="今年销量是多少？",
            session_id=session_id,
            idempotency_key=None,
        ).run
        runs.transition(run_id=run.id, target=RunStatus.RUNNING)
        runs.transition(run_id=run.id, target=RunStatus.WAITING_CLARIFICATION)
        case = ClarificationCase.open(
            case_id=case_id,
            run_id=run.id,
            session_id=session_id,
            frame_id="frame-waiting",
            questions=(
                ClarificationQuestion(
                    question_id="domain",
                    prompt="这个问题可能属于多个数据域，请确认口径。",
                    reason=ClarificationReason.MUTUALLY_EXCLUSIVE_DOMAINS,
                    choices=(
                        ClarificationChoice(
                            choice_id="actual",
                            label="Actual 实际销售",
                            explanation="内部实际销售口径",
                        ),
                        ClarificationChoice(
                            choice_id="demand",
                            label="Demand",
                        ),
                    ),
                ),
            ),
            created_at=datetime.now(timezone.utc),
        )
        SqlAlchemyClarificationRepository(database).save(case)
        # The suspended checkpoint the resume job will continue from.
        SqlAlchemyArtifactRepository(database).append(
            run_id=run.id,
            kind="agent_transcript",
            payload={
                "turn_messages": [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"id": "call-waiting", "name": "ask_user", "arguments": "{}"}
                        ],
                    }
                ],
                "status": "suspended",
                "step": 1,
                "prompt_version": "agent-v1",
                "pending": {
                    "call_id": "call-waiting",
                    "name": "ask_user",
                    "case_id": case_id,
                },
            },
        )
        event = runs.append_event(
            run_id=run.id,
            event_type="clarification.required",
            payload={
                "case_id": case.case_id,
                "run_id": case.run_id,
                "groups": [],
            },
        )
    return case_id, run.id, session_id, event.cursor


def test_waiting_clarifications_restore_event_shape_and_cursor(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    owner = seed_user("clarification-owner")
    case_id, run_id, session_id, cursor = _seed_waiting_clarification(app, owner)

    by_session = client.get(
        f"/api/v2/clarifications/waiting?session_id={session_id}",
        headers=auth_headers("clarification-owner"),
    )
    by_run = client.get(
        f"/api/v2/clarifications/waiting?run_id={run_id}",
        headers=auth_headers("clarification-owner"),
    )

    assert by_session.status_code == 200, by_session.text
    assert by_run.status_code == 200, by_run.text
    assert by_run.json() == by_session.json()
    payload = by_session.json()[0]
    assert payload["case_id"] == case_id
    assert payload["run_id"] == run_id
    assert payload["session_id"] == session_id
    assert payload["events_url"] == f"/api/v2/runs/{run_id}/stream"
    assert payload["last_event_cursor"] == cursor
    assert payload["groups"] == [
        {
            "question_id": "domain",
            "prompt": "这个问题可能属于多个数据域，请确认口径。",
            "why": "",
            "required": True,
            "allow_free_text": False,
            "multi_select": False,
            "choices": [
                {
                    "id": "actual",
                    "label": "Actual 实际销售",
                    "explanation": "内部实际销售口径",
                    "recommended": False,
                    "source": None,
                },
                {
                    "id": "demand",
                    "label": "Demand",
                    "explanation": None,
                    "recommended": False,
                    "source": None,
                },
            ],
        }
    ]


def test_waiting_clarifications_are_owner_scoped(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    owner = seed_user("clarification-owner")
    seed_user("clarification-other")
    _, run_id, session_id, _ = _seed_waiting_clarification(app, owner)

    unfiltered = client.get(
        "/api/v2/clarifications/waiting",
        headers=auth_headers("clarification-other"),
    )
    by_run = client.get(
        f"/api/v2/clarifications/waiting?run_id={run_id}",
        headers=auth_headers("clarification-other"),
    )
    by_session = client.get(
        f"/api/v2/clarifications/waiting?session_id={session_id}",
        headers=auth_headers("clarification-other"),
    )

    assert unfiltered.status_code == 200
    assert unfiltered.json() == []
    assert by_run.status_code == 200
    assert by_run.json() == []
    assert by_session.status_code == 200
    assert by_session.json() == []


def test_clarification_answer_requires_at_least_one_answer_form(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    seed_user("clarifier")

    response = client.post(
        "/api/v2/clarifications/missing/answers",
        json={"answers": [{"question_id": "domain"}]},
        headers=auth_headers("clarifier"),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "answer",
    [
        {"question_id": "domain", "choice_ids": ["actual", "demand"]},
        {"question_id": "domain", "choice_id": "actual", "free_text": "actual"},
    ],
)
def test_clarification_accepts_choice_ids_or_choice_plus_free_text(
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
    answer: dict[str, object],
) -> None:
    seed_user("clarifier")

    response = client.post(
        "/api/v2/clarifications/missing/answers",
        json={"answers": [answer]},
        headers=auth_headers("clarifier"),
    )

    # Request body is valid; the case itself is not there.
    assert response.status_code == 422


def test_clarification_submit_enqueues_a_resume_job(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    owner = seed_user("clarification-owner")
    case_id, run_id, session_id, _ = _seed_waiting_clarification(app, owner)

    response = client.post(
        f"/api/v2/clarifications/{case_id}/answers",
        json={"answers": [{"question_id": "domain", "choice_id": "actual"}]},
        headers=auth_headers("clarification-owner"),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["run_id"] == run_id
    assert body["session_id"] == session_id
    with session_scope(app.state.session_factory) as database:
        job = SqlAlchemyJobRepository(database).find_by_deduplication_key(f"quick:resume:{case_id}")
        assert job is not None
        assert job.payload["answer"] == (
            "问：这个问题可能属于多个数据域，请确认口径。\n答：Actual 实际销售"
        )
        assert job.payload["answers"] == [{"question_id": "domain", "text": "Actual 实际销售"}]


def test_clarification_submit_rejects_an_already_handled_case(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    owner = seed_user("clarification-owner")
    case_id, _, _, _ = _seed_waiting_clarification(app, owner)

    first = client.post(
        f"/api/v2/clarifications/{case_id}/answers",
        json={"answers": [{"question_id": "domain", "choice_id": "actual"}]},
        headers=auth_headers("clarification-owner"),
    )
    assert first.status_code == 202, first.text
    # The resume job consumes the case; a second submit must be refused safely.
    for _ in range(40):
        with session_scope(app.state.session_factory) as database:
            case = SqlAlchemyClarificationRepository(database).get(case_id)
        if case is not None and case.status.value != "waiting":
            break
        time.sleep(0.1)

    second = client.post(
        f"/api/v2/clarifications/{case_id}/answers",
        json={"answers": [{"question_id": "domain", "choice_id": "demand"}]},
        headers=auth_headers("clarification-owner"),
    )

    assert second.status_code == 422
    assert second.json()["error"]["code"] == "VALIDATION_FAILED"


def test_chat_models_lists_choices_without_secrets(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    from xiaoying_quick.infrastructure.persistence.repositories.model_configs import (
        SqlAlchemyModelConfigRepository,
    )
    from xiaoying_quick.modules.models import ModelConfigRecord

    with session_scope(app.state.session_factory) as database:
        SqlAlchemyModelConfigRepository(database).add(
            ModelConfigRecord(
                id="model-choice-1",
                name="bailian",
                endpoint_url="https://llm.example/v1/chat/completions",
                model_id="qwen3.7-max",
                secret_ref="secret-ref-1",
                temperature=0.2,
                max_tokens=16_384,
                reasoning="off",
                timeout_seconds=180.0,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    seed_user("model-picker")

    response = client.get("/api/v2/chat/models", headers=auth_headers("model-picker"))

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "id": "model-choice-1",
            "name": "bailian",
            "model_id": "qwen3.7-max",
            "is_active": True,
        }
    ]


def test_chat_request_carries_model_options_into_the_job(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    seed_user("model-options-owner")

    response = client.post(
        "/api/v2/chat",
        json={
            "question": "安达唐今年 YTD 达成率？",
            "model_config_id": "model-choice-1",
            "thinking": "on",
            "thinking_level": "high",
        },
        headers={**auth_headers("model-options-owner"), "Idempotency-Key": "opts-1"},
    )

    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    with session_scope(app.state.session_factory) as database:
        job = SqlAlchemyJobRepository(database).find_by_deduplication_key(f"quick:start:{run_id}")
    assert job is not None
    assert job.payload["model_options"] == {
        "model_config_id": "model-choice-1",
        "thinking": "on",
        "thinking_level": "high",
    }


def test_chat_request_can_disable_personal_memory(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    seed_user("eval-owner")

    response = client.post(
        "/api/v2/chat",
        json={"question": "安达唐今年销量？", "use_memory": False},
        headers={**auth_headers("eval-owner"), "Idempotency-Key": "eval-no-mem"},
    )

    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    with session_scope(app.state.session_factory) as database:
        job = SqlAlchemyJobRepository(database).find_by_deduplication_key(f"quick:start:{run_id}")
    assert job is not None
    assert job.payload["model_options"]["use_memory"] == "false"


def test_clarification_submit_keeps_model_options(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    owner = seed_user("clarification-models-owner")
    case_id, run_id, _, _ = _seed_waiting_clarification(app, owner)

    response = client.post(
        f"/api/v2/clarifications/{case_id}/answers",
        json={
            "answers": [{"question_id": "domain", "choice_id": "actual"}],
            "model_config_id": "model-choice-1",
            "thinking": "off",
        },
        headers=auth_headers("clarification-models-owner"),
    )

    assert response.status_code == 202, response.text
    with session_scope(app.state.session_factory) as database:
        job = SqlAlchemyJobRepository(database).find_by_deduplication_key(f"quick:resume:{case_id}")
    assert job is not None
    assert job.payload["model_options"] == {
        "model_config_id": "model-choice-1",
        "thinking": "off",
    }


def test_chat_questions_are_paginated_and_owner_scoped(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    from xiaoying_quick.modules.chat.contracts import MessageRole

    owner = seed_user("question-owner")
    other = seed_user("question-other")
    with session_scope(app.state.session_factory) as database:
        chats = SqlAlchemyChatRepository(database)
        own_session = chats.create_session("session-questions", owner.id, "安达唐销量")
        other_session = chats.create_session("session-other-questions", other.id, "别人的问题")
        chats.append_message("m-other", other_session.id, MessageRole.USER, "别人问的")
        chats.append_message("m-assistant", own_session.id, MessageRole.ASSISTANT, "这不是问题")
        for index in range(25):
            chats.append_message(
                f"m-{index:02d}",
                own_session.id,
                MessageRole.USER,
                f"问题{index}",
            )

    page1 = client.get(
        "/api/v2/chat/questions?limit=20&offset=0",
        headers=auth_headers("question-owner"),
    )
    page2 = client.get(
        "/api/v2/chat/questions?limit=20&offset=20",
        headers=auth_headers("question-owner"),
    )
    other_page = client.get(
        "/api/v2/chat/questions",
        headers=auth_headers("question-other"),
    )

    assert page1.status_code == 200, page1.text
    body = page1.json()
    assert body["total"] == 25
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["content"] for item in body["items"]] == [
        f"问题{index}" for index in range(24, 4, -1)
    ]
    assert all(item["session_id"] == "session-questions" for item in body["items"])
    assert all(item["session_title"] == "安达唐销量" for item in body["items"])
    assert page2.status_code == 200, page2.text
    assert [item["content"] for item in page2.json()["items"]] == [
        f"问题{index}" for index in range(4, -1, -1)
    ]
    assert other_page.status_code == 200, other_page.text
    assert other_page.json()["total"] == 1
    assert other_page.json()["items"][0]["content"] == "别人问的"
