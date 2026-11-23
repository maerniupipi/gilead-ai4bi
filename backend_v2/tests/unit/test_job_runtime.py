from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

from xiaoying_quick.bootstrap.job_runtime import DurableJobRuntime
from xiaoying_quick.bootstrap.jobs import dispatch_job, execute_durable_job
from xiaoying_quick.modules.jobs import JobStatus


class _Background:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple]] = []

    def add_task(self, func, *args) -> None:
        self.calls.append((func, args))


def test_drain_ready_submits_a_backlog_ahead_of_live_workers(monkeypatch) -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(job_poll_seconds=0.5, job_max_workers=2),
            session_factory=None,
        )
    )
    runtime = DurableJobRuntime(app)
    jobs = (
        SimpleNamespace(id="job-a", status=JobStatus.PENDING),
        SimpleNamespace(id="job-b", status=JobStatus.PENDING),
        SimpleNamespace(id="job-c", status=JobStatus.PENDING),
    )

    @contextmanager
    def fake_scope(_factory):
        yield None

    monkeypatch.setattr("xiaoying_quick.bootstrap.job_runtime.session_scope", fake_scope)
    monkeypatch.setattr(
        "xiaoying_quick.bootstrap.job_runtime.build_job_service",
        lambda _database, _app: SimpleNamespace(ready=lambda limit: jobs[:limit]),
    )
    submitted: list[str] = []
    monkeypatch.setattr(runtime, "submit", lambda job_id: submitted.append(job_id) or True)

    assert runtime._drain_ready() == 3
    assert submitted == ["job-a", "job-b", "job-c"]
    runtime._executor.shutdown(wait=False)


def test_submit_queues_past_the_live_worker_cap() -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(job_poll_seconds=0.5, job_max_workers=1),
            session_factory=None,
        )
    )
    runtime = DurableJobRuntime(app)
    started = threading.Event()
    release = threading.Event()

    def fake_run(_job_id: str) -> bool:
        started.set()
        release.wait(timeout=2)
        return True

    runtime._run_one = fake_run
    assert runtime.submit("job-a") is True
    assert started.wait(timeout=1)
    assert runtime.submit("job-b") is True
    release.set()
    runtime._executor.shutdown(wait=True)


def test_wake_from_another_thread_is_threadsafe() -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(job_poll_seconds=0.5, job_max_workers=1),
            session_factory=None,
        )
    )
    runtime = DurableJobRuntime(app)

    async def main() -> None:
        runtime._loop = asyncio.get_running_loop()
        pinged = threading.Event()

        def ping() -> None:
            runtime.wake()
            pinged.set()

        threading.Thread(target=ping, daemon=True).start()
        await asyncio.wait_for(runtime._wake.wait(), timeout=1)
        assert pinged.wait(timeout=1)

    asyncio.run(main())
    runtime._executor.shutdown(wait=False)


def test_dispatch_job_does_not_pin_http_outside_tests() -> None:
    submitted: list[str] = []
    runtime = SimpleNamespace(
        submit=lambda job_id: submitted.append(job_id) or True,
        wake=lambda: submitted.append("wake"),
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(environment="development"),
            job_runtime=runtime,
        )
    )
    background = _Background()
    dispatch_job(app, "job-1", background)
    assert submitted == ["job-1", "wake"]
    assert background.calls == []


def test_dispatch_job_stays_inline_for_testclient() -> None:
    runtime = SimpleNamespace(submit=lambda _job_id: True, wake=lambda: None)
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(environment="test"),
            job_runtime=runtime,
        )
    )
    background = _Background()
    dispatch_job(app, "job-2", background)
    assert background.calls == [(execute_durable_job, (app, "job-2"))]
