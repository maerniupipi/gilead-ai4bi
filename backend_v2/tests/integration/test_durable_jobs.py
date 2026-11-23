"""Durable Quick job queue, claim, and recovery integration tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from xiaoying_quick.app import create_app
from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.llm.client import (
    AssistantTurn,
    ContentDelta,
    TurnComplete,
)
from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.repositories.chat import SqlAlchemyChatRepository
from xiaoying_quick.infrastructure.persistence.repositories.identity import (
    SqlAlchemyUserRepository,
)
from xiaoying_quick.infrastructure.persistence.repositories.jobs import SqlAlchemyJobRepository
from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from xiaoying_quick.modules.identity.contracts import (
    AuthenticatedPrincipal,
    Role,
    UserRecord,
)
from xiaoying_quick.modules.jobs import JobService, JobStatus
from xiaoying_quick.modules.runs.service import RunService
from xiaoying_quick.shared.clock import FrozenClock


class FakeModelClient:
    """One canned single-step answer, so jobs finish without a live endpoint."""

    async def stream_chat(
        self,
        *,
        purpose: str,
        messages,
        tools=None,
        max_tokens: int | None = None,
    ):
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


def test_chat_run_is_backed_by_one_succeeded_durable_job(
    app: FastAPI,
    client: TestClient,
    seed_user: Callable[..., UserRecord],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    app.state.model_registry = FakeModelRegistry()
    seed_user("durable-owner")

    first = client.post(
        "/api/v2/chat",
        headers={
            **auth_headers("durable-owner"),
            "Idempotency-Key": "durable-chat-1",
        },
        json={"question": "Actual 域安达唐 2025 年 7 月销售额是多少？"},
    )
    second = client.post(
        "/api/v2/chat",
        headers={
            **auth_headers("durable-owner"),
            "Idempotency-Key": "durable-chat-1",
        },
        json={"question": "Actual 域安达唐 2025 年 7 月销售额是多少？"},
    )

    assert first.status_code == 202, first.text
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] == first.json()["run_id"]
    with session_scope(app.state.session_factory) as database:
        job = SqlAlchemyJobRepository(database).find_by_deduplication_key(
            f"quick:start:{first.json()['run_id']}"
        )
        assert job is not None
        assert job.status is JobStatus.SUCCEEDED
        assert job.attempt_count == 1
        assert job.locked_by is None
        assert job.completed_at is not None


def test_compare_and_set_claim_prevents_duplicate_workers(
    app: FastAPI,
    seed_user: Callable[..., UserRecord],
) -> None:
    Base.metadata.create_all(app.state.engine)
    owner = seed_user("claim-owner")
    job_id = _seed_pending_job(app, owner, "claim")

    with session_scope(app.state.session_factory) as database:
        first = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
        ).claim(job_id, worker_id="worker-one")
        assert first is not None
        assert first.status is JobStatus.RUNNING
        assert first.attempt_count == 1

    with session_scope(app.state.session_factory) as database:
        second = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
        ).claim(job_id, worker_id="worker-two")
        assert second is None


def test_expired_running_lease_is_requeued_and_can_be_reclaimed(
    app: FastAPI,
    seed_user: Callable[..., UserRecord],
) -> None:
    Base.metadata.create_all(app.state.engine)
    owner = seed_user("recovery-owner")
    started_at = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)
    job_id = _seed_pending_job(app, owner, "recover", now=started_at)

    with session_scope(app.state.session_factory) as database:
        claimed = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
            clock=FrozenClock(started_at),
            lease_seconds=30,
        ).claim(job_id, worker_id="dead-worker")
        assert claimed is not None

    recovered_at = started_at + timedelta(seconds=31)
    with session_scope(app.state.session_factory) as database:
        service = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
            clock=FrozenClock(recovered_at),
            lease_seconds=30,
        )
        assert service.recover_stale() == 1
        recovered = SqlAlchemyJobRepository(database).get(job_id)
        assert recovered is not None
        assert recovered.status is JobStatus.PENDING
        assert recovered.locked_by is None
        assert recovered.last_error_code == "LEASE_EXPIRED"

    with session_scope(app.state.session_factory) as database:
        reclaimed = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
            clock=FrozenClock(recovered_at),
            lease_seconds=30,
        ).claim(job_id, worker_id="replacement-worker")
        assert reclaimed is not None
        assert reclaimed.status is JobStatus.RUNNING
        assert reclaimed.attempt_count == 2


def test_application_startup_recovers_and_executes_an_expired_job(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "restart-recovery.sqlite3"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path}",
        db_auto_create=True,
        auth_hmac_secret=SecretStr("restart-auth-secret-with-at-least-32-bytes"),
        sql_approval_hmac_secret=SecretStr("restart-sql-secret-independent-and-at-least-32-bytes"),
        secret_store_path=tmp_path / "secrets.json",
        secret_key_path=tmp_path / "master.key",
        knowledge_root=tmp_path / "knowledge",
        job_poll_seconds=0.05,
        job_retry_delay_seconds=0,
    )
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    Base.metadata.create_all(engine)
    created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    owner = UserRecord(
        id="user-restart",
        username="restart-owner",
        username_key="restart-owner",
        display_name="Restart Owner",
        password_digest="not-used-by-this-test",
        role=Role.USER,
        is_active=True,
        created_at=created_at,
    )
    with session_scope(factory) as database:
        SqlAlchemyUserRepository(database).add(owner)
    staging_app = create_app(settings=settings, engine=engine, session_factory=factory)
    job_id = _seed_pending_job(staging_app, owner, "restart", now=created_at)
    with session_scope(factory) as database:
        claimed = JobService(
            SqlAlchemyJobRepository(database),
            lambda: "unused",
            clock=FrozenClock(created_at),
            lease_seconds=30,
        ).claim(job_id, worker_id="worker-before-crash")
        assert claimed is not None
        assert claimed.status is JobStatus.RUNNING

    application = create_app(settings=settings, engine=engine, session_factory=factory)
    application.state.model_registry = FakeModelRegistry()
    with TestClient(application):
        deadline = time.monotonic() + 5
        recovered = None
        while time.monotonic() < deadline:
            with session_scope(factory) as database:
                recovered = SqlAlchemyJobRepository(database).get(job_id)
            if recovered is not None and recovered.status.is_terminal:
                break
            time.sleep(0.05)

        assert recovered is not None
        assert recovered.status is JobStatus.SUCCEEDED
        assert recovered.attempt_count == 2
        assert recovered.last_error_code is None


def test_execute_durable_job_renews_lease_while_running(
    app: FastAPI,
    seed_user: Callable[..., UserRecord],
    monkeypatch,
) -> None:
    from xiaoying_quick.bootstrap import jobs as jobs_mod

    owner = seed_user("lease-owner")
    job_id = _seed_pending_job(app, owner, "heartbeat")
    app.state.settings = app.state.settings.model_copy(update={"job_heartbeat_seconds": 0.05})
    monkeypatch.setattr(jobs_mod, "_execute_claimed", lambda *_args, **_kwargs: time.sleep(0.22))
    renews: list[str] = []
    original = JobService.renew

    def tracking(self, tracked_job_id, *, worker_id):
        renews.append(tracked_job_id)
        return original(self, tracked_job_id, worker_id=worker_id)

    monkeypatch.setattr(JobService, "renew", tracking)
    assert jobs_mod.execute_durable_job(app, job_id) is True
    assert renews, "a job that outlives the heartbeat interval must renew its lease"


def _seed_pending_job(
    app: FastAPI,
    owner: UserRecord,
    suffix: str,
    *,
    now: datetime | None = None,
) -> str:
    principal = AuthenticatedPrincipal(
        user_id=owner.id,
        username=owner.username,
        display_name=owner.display_name,
        role=owner.role,
    )
    with session_scope(app.state.session_factory) as database:
        session_id = f"session-{suffix}"
        SqlAlchemyChatRepository(database).create_session(session_id, owner.id, suffix)
        run = (
            RunService(
                SqlAlchemyRunRepository(database),
                clock=FrozenClock(now) if now is not None else None,
            )
            .create_run(
                principal=principal,
                question="Actual 域销售额是多少？",
                session_id=session_id,
                idempotency_key=f"run-{suffix}",
            )
            .run
        )
        service = JobService(
            SqlAlchemyJobRepository(database),
            lambda: f"job-{suffix}",
            clock=FrozenClock(now) if now is not None else None,
        )
        return service.enqueue_start(
            run_id=run.id,
            owner_user_id=owner.id,
            session_id=session_id,
            question=run.question,
        ).id
