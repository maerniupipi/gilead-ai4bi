"""Durable Quick-job enqueueing and one-job execution entry points."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from fastapi import BackgroundTasks, FastAPI

from ..infrastructure.llm.errors import LlmError
from ..infrastructure.persistence.repositories.chat import SqlAlchemyChatRepository
from ..infrastructure.persistence.repositories.identity import SqlAlchemyUserRepository
from ..infrastructure.persistence.repositories.jobs import SqlAlchemyJobRepository
from ..infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from ..infrastructure.persistence.session import session_scope
from ..modules.identity.contracts import AuthenticatedPrincipal
from ..modules.identity.service import IdentityService
from ..modules.jobs import JobKind, JobRecord, JobService, JobStatus
from ..modules.runs import RunStatus
from ..modules.runs.service import RunService
from ..shared.ids import new_id

_LOGGER = logging.getLogger(__name__)


class PermanentJobError(RuntimeError):
    """A safe, non-retryable durable-job failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_job_service(database: Any, app: FastAPI) -> JobService:
    settings = app.state.settings
    return JobService(
        SqlAlchemyJobRepository(database),
        lambda: new_id("job"),
        lease_seconds=settings.job_lease_seconds,
        retry_delay_seconds=settings.job_retry_delay_seconds,
    )


def enqueue_quick_start(
    *,
    app: FastAPI,
    database: Any,
    principal: AuthenticatedPrincipal,
    run_id: str,
    session_id: str,
    question: str,
    model_config_id: str | None = None,
    thinking: str | None = None,
    thinking_level: str | None = None,
    use_memory: bool | None = None,
    mode: str | None = None,
    insight_custom_prompt: str | None = None,
    insight_skill_pack_id: str | None = None,
) -> JobRecord:
    options = _model_options_payload(model_config_id, thinking, thinking_level, use_memory)
    if mode:
        options["mode"] = str(mode)[:16]
    if insight_custom_prompt:
        options["insight_custom_prompt"] = str(insight_custom_prompt)[:20_000]
    if insight_skill_pack_id:
        options["insight_skill_pack_id"] = str(insight_skill_pack_id)[:64]
    return build_job_service(database, app).enqueue_start(
        run_id=run_id,
        owner_user_id=principal.user_id,
        session_id=session_id,
        question=question,
        model_options=options,
    )


def enqueue_quick_resume(
    *,
    app: FastAPI,
    database: Any,
    principal: AuthenticatedPrincipal,
    run_id: str,
    session_id: str,
    case_id: str,
    answer: str,
    answers: tuple[dict[str, str], ...] = (),
    model_config_id: str | None = None,
    thinking: str | None = None,
    thinking_level: str | None = None,
    use_memory: bool | None = None,
) -> JobRecord:
    return build_job_service(database, app).enqueue_resume(
        run_id=run_id,
        owner_user_id=principal.user_id,
        session_id=session_id,
        case_id=case_id,
        answer=answer,
        answers=answers,
        model_options=_model_options_payload(model_config_id, thinking, thinking_level, use_memory),
    )


def _model_options_payload(
    model_config_id: str | None,
    thinking: str | None,
    thinking_level: str | None,
    use_memory: bool | None = None,
) -> dict[str, str]:
    options: dict[str, str] = {}
    if model_config_id:
        options["model_config_id"] = str(model_config_id)[:64]
    if thinking in ("on", "off", "default"):
        options["thinking"] = thinking
    if thinking_level in ("low", "medium", "high"):
        options["thinking_level"] = thinking_level
    if use_memory is False:
        options["use_memory"] = "false"
    return options


def dispatch_job(app: FastAPI, job_id: str, background: BackgroundTasks | None = None) -> None:
    """Kick a pending job without waiting for the HTTP request.

    FastAPI background tasks run *after* the response is sent but *before* the
    ASGI call returns, so they pin the HTTP/1.1 connection for the whole agent
    loop. Production therefore submits onto the in-process pool and returns.
    Tests keep the inline background task so TestClient can wait for success.
    """

    settings = getattr(app.state, "settings", None)
    runtime = getattr(app.state, "job_runtime", None)
    if background is not None and getattr(settings, "environment", None) == "test":
        background.add_task(execute_durable_job, app, job_id)
        return

    submit = getattr(runtime, "submit", None)
    if callable(submit):
        submit(job_id)
    wake = getattr(runtime, "wake", None)
    if callable(wake):
        wake()
    elif background is not None and runtime is None:
        background.add_task(execute_durable_job, app, job_id)


def job_heartbeat_interval(settings: Any) -> float:
    if settings is None:
        return 5.0
    explicit = float(getattr(settings, "job_heartbeat_seconds", 0) or 0)
    if explicit > 0:
        return explicit
    lease = int(getattr(settings, "job_lease_seconds", 180) or 180)
    return max(5.0, lease / 3)


def execute_durable_job(
    app: FastAPI,
    job_id: str,
    worker_id: str | None = None,
) -> bool:
    """Claim and execute one job; return false when another worker owns it."""

    worker = worker_id or new_id("worker")
    stop_heartbeat = threading.Event()
    heartbeat: threading.Thread | None = None
    claimed: JobRecord | None = None
    try:
        with session_scope(app.state.session_factory) as database:
            claimed = build_job_service(database, app).claim(job_id, worker_id=worker)
            if claimed is None:
                return False
            RunService(SqlAlchemyRunRepository(database)).append_event(
                run_id=claimed.run_id,
                event_type="job.claimed",
                payload={
                    "job_id": claimed.id,
                    "kind": claimed.kind.value,
                    "attempt": claimed.attempt_count,
                },
            )

        heartbeat = threading.Thread(
            target=_renew_lease_until,
            args=(app, claimed.id, worker, stop_heartbeat),
            name=f"job-lease-{claimed.id}",
            daemon=True,
        )
        heartbeat.start()

        try:
            _execute_claimed(app, claimed)
        except Exception as exc:
            if isinstance(exc, PermanentJobError):
                permanent = True
                code = exc.code
                message = str(exc.code)
            elif isinstance(exc, LlmError):
                # Non-retryable provider errors (e.g. 402 balance) should fail closed.
                permanent = not exc.retryable
                code = f"JOB_LLM_{exc.code.value.upper()}"[:96]
                message = _llm_user_message(exc)
                _LOGGER.warning(
                    "durable job llm failure run=%s code=%s status=%s detail=%s",
                    claimed.run_id,
                    exc.code.value,
                    exc.status_code,
                    (exc.detail or "")[:400],
                )
            else:
                permanent = False
                code = _safe_error_code(exc)
                message = "Durable Quick job failed closed"
                _LOGGER.warning(
                    "durable job failed run=%s code=%s",
                    claimed.run_id,
                    code,
                    exc_info=True,
                )
            with session_scope(app.state.session_factory) as database:
                service = build_job_service(database, app)
                updated = service.fail(
                    claimed,
                    worker_id=worker,
                    error_code=code,
                    terminal=permanent,
                )
                if updated is not None:
                    RunService(SqlAlchemyRunRepository(database)).append_event(
                        run_id=claimed.run_id,
                        event_type=(
                            "job.failed" if updated.status is JobStatus.FAILED else "job.retrying"
                        ),
                        payload={
                            "job_id": claimed.id,
                            "kind": claimed.kind.value,
                            "attempt": claimed.attempt_count,
                            "code": code,
                            "message": message,
                        },
                    )
                    if updated.status is JobStatus.FAILED:
                        _fail_nonterminal_run(
                            database, claimed.run_id, code, message=message
                        )
            return True

        with session_scope(app.state.session_factory) as database:
            updated = build_job_service(database, app).succeed(claimed.id, worker_id=worker)
            if updated is not None:
                RunService(SqlAlchemyRunRepository(database)).append_event(
                    run_id=claimed.run_id,
                    event_type="job.succeeded",
                    payload={
                        "job_id": claimed.id,
                        "kind": claimed.kind.value,
                        "attempt": claimed.attempt_count,
                    },
                )
        return True
    finally:
        stop_heartbeat.set()
        if heartbeat is not None:
            heartbeat.join(timeout=1)


def _renew_lease_until(
    app: FastAPI,
    job_id: str,
    worker_id: str,
    stop: threading.Event,
) -> None:
    """Keep a long agent loop from looking dead to recover_stale."""

    interval = job_heartbeat_interval(getattr(app.state, "settings", None))
    while not stop.wait(interval):
        try:
            with session_scope(app.state.session_factory) as database:
                if not build_job_service(database, app).renew(job_id, worker_id=worker_id):
                    return
        except Exception:
            _LOGGER.warning("job lease renew failed", exc_info=True)


def _execute_claimed(app: FastAPI, job: JobRecord) -> None:
    from ..application.agent_run import AgentModelUnavailable
    from .container import build_agent_service

    with session_scope(app.state.session_factory) as database:
        user = SqlAlchemyUserRepository(database).get_by_id(job.owner_user_id)
        if user is None or not user.is_active:
            raise PermanentJobError("JOB_OWNER_UNAVAILABLE")
        run = SqlAlchemyRunRepository(database).get(job.run_id)
        if run is None or run.owner_user_id != job.owner_user_id:
            raise PermanentJobError("JOB_RUN_UNAVAILABLE")

        if run.status.is_terminal:
            return

        session_id = _required_payload_string(job.payload, "session_id")
        chat_session = SqlAlchemyChatRepository(database).get_session(session_id)
        if chat_session is None or chat_session.owner_id != job.owner_user_id:
            raise PermanentJobError("JOB_SESSION_UNAVAILABLE")
        principal = IdentityService.principal_from_user(user)

        agent = build_agent_service(database, app, run_id=job.run_id)
        try:
            _run_agent_job(agent, job, run, chat_session, principal)
        except AgentModelUnavailable:
            # No active model configuration is an operational fact, not a
            # transient glitch: the run is already failed, so stop retrying.
            raise PermanentJobError("NO_ACTIVE_MODEL") from None


def _run_agent_job(
    agent: Any,
    job: JobRecord,
    run: Any,
    chat_session: Any,
    principal: AuthenticatedPrincipal,
) -> None:
    if job.kind is JobKind.START_QUICK_RUN:
        question = _required_payload_string(job.payload, "question", max_length=10_000)
        if run.status not in (RunStatus.RECEIVED, RunStatus.RUNNING):
            raise PermanentJobError("JOB_START_STATE_INVALID")
        # RUNNING means a previous attempt crashed; start() continues from
        # the transcript checkpoint it left behind.
        asyncio.run(
            agent.start(
                principal=principal,
                run_id=job.run_id,
                session=chat_session,
                question=question,
                **_model_options(job.payload),
            )
        )
        return

    if job.kind is JobKind.RESUME_QUICK_RUN:
        if run.status not in (RunStatus.WAITING_CLARIFICATION, RunStatus.RUNNING):
            raise PermanentJobError("JOB_RESUME_STATE_INVALID")
        answer = _payload_text(job.payload, "answer", max_length=2_000)
        if not answer.strip():
            raise PermanentJobError("JOB_ANSWER_INVALID")
        asyncio.run(
            agent.resume(
                principal=principal,
                run_id=job.run_id,
                session=chat_session,
                answer=answer,
                answers=_payload_answers(job.payload),
                **_model_options(job.payload),
            )
        )
        return

    raise PermanentJobError("JOB_KIND_UNSUPPORTED")


def _model_options(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("model_options")
    if not isinstance(raw, dict):
        return {}
    options: dict[str, Any] = {}
    model_config_id = raw.get("model_config_id")
    if isinstance(model_config_id, str) and model_config_id.strip():
        options["model_config_id"] = model_config_id.strip()[:64]
    thinking = raw.get("thinking")
    if thinking in ("on", "off", "default"):
        options["thinking"] = thinking
    level = raw.get("thinking_level")
    if level in ("low", "medium", "high"):
        options["thinking_level"] = level
    raw_memory = raw.get("use_memory")
    if raw_memory in (False, "false", "0"):
        options["use_memory"] = False
    elif raw_memory in (True, "true", "1"):
        options["use_memory"] = True
    return options


def _fail_nonterminal_run(
    database: Any,
    run_id: str,
    code: str,
    *,
    message: str | None = None,
) -> None:
    runs = RunService(SqlAlchemyRunRepository(database))
    run = SqlAlchemyRunRepository(database).get(run_id)
    if run is None or run.status.is_terminal or run.status is RunStatus.WAITING_CLARIFICATION:
        return
    try:
        runs.append_event(
            run_id=run_id,
            event_type="quick.failed",
            payload={
                "code": code,
                "message": message or "Durable Quick job failed closed",
            },
        )
        runs.transition(run_id=run_id, target=RunStatus.FAILED)
    except Exception:
        return


def _llm_user_message(exc: LlmError) -> str:
    detail = (exc.detail or "").lower()
    if exc.status_code == 402 or "insufficient balance" in detail:
        return "模型服务余额不足（DeepSeek Insufficient Balance），请充值或在「模型管理」切换可用模型后重试。"
    if exc.code.value == "rate_limited" or exc.status_code == 429:
        return "模型服务限流，请稍后再试。"
    if exc.code.value == "timeout":
        return "模型调用超时，请稍后重试。"
    if exc.code.value == "network_error":
        return "模型网络异常，请检查网络或接口地址后重试。"
    snippet = (exc.detail or "").strip()
    if snippet:
        return f"模型调用失败（{exc.code.value}）：{snippet[:240]}"
    return f"模型调用失败（{exc.code.value}），请在运行轨迹中查看详情后重试。"


def _required_payload_string(
    payload: dict[str, Any],
    key: str,
    *,
    max_length: int = 128,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise PermanentJobError("JOB_PAYLOAD_INVALID")
    clean = value.strip()
    if not clean or len(clean) > max_length or any(ord(character) < 32 for character in clean):
        raise PermanentJobError("JOB_PAYLOAD_INVALID")
    return clean


def _payload_text(payload: dict[str, Any], key: str, *, max_length: int = 20_000) -> str:
    """Free prose from the payload: optional, possibly long, never structural."""

    value = payload.get(key)
    return value[:max_length] if isinstance(value, str) else ""


def _payload_answers(payload: dict[str, Any]) -> dict[str, str]:
    """Per-question clarification answers; empty on legacy payloads."""

    raw = payload.get("answers")
    if not isinstance(raw, list):
        return {}
    answers: dict[str, str] = {}
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        text = str(item.get("text") or "").strip()[:2_000]
        if question_id and text:
            answers[question_id] = text
    return answers


def _safe_error_code(exc: Exception) -> str:
    name = type(exc).__name__.upper()
    sanitized = "".join(character if character.isalnum() else "_" for character in name)
    return f"JOB_{sanitized[:80] or 'EXECUTION_ERROR'}"


__all__ = [
    "build_job_service",
    "dispatch_job",
    "enqueue_quick_resume",
    "enqueue_quick_start",
    "execute_durable_job",
    "job_heartbeat_interval",
]
