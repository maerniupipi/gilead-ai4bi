"""Process-local polling runtime backed by the durable Quick job table."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from fastapi import FastAPI

from ..infrastructure.persistence.session import session_scope
from ..modules.jobs import JobStatus
from ..shared.ids import new_id
from .jobs import build_job_service, execute_durable_job

_LOGGER = logging.getLogger(__name__)
_MAX_QUEUED_JOBS = 256


class DurableJobRuntime:
    """Recover expired leases and dispatch pending durable jobs in parallel.

    Database compare-and-set claims remain the source of truth. The in-process
    pool is only a delivery mechanism, so multiple API processes can poll the
    same table without executing one job concurrently.
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        settings = app.state.settings
        self._poll_seconds = float(settings.job_poll_seconds)
        self._max_workers = int(getattr(settings, "job_max_workers", 8) or 8)
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._worker_prefix = new_id("worker")
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="quick-job",
        )
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future[bool]] = {}
        self._closed = threading.Event()

    def wake(self) -> None:
        """Wake the poller from the event loop or a worker/HTTP thread."""

        event = self._wake
        loop = self._loop
        if loop is None or loop.is_closed():
            try:
                event.set()
            except Exception:
                _LOGGER.debug("job runtime wake ignored", exc_info=True)
            return
        try:
            if asyncio.get_running_loop() is loop:
                event.set()
                return
        except RuntimeError:
            pass
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            _LOGGER.debug("job runtime wake skipped; loop closed", exc_info=True)

    def submit(self, job_id: str) -> bool:
        """Queue one pending job onto the worker pool.

        The executor already caps live workers. Refusing extra jobs here used
        to drop HTTP dispatches and then depend on the poller; if the poller
        stalled, pending rows sat forever.
        """

        if self._closed.is_set():
            return False
        with self._lock:
            if self._closed.is_set() or job_id in self._in_flight:
                return False
            if len(self._in_flight) >= _MAX_QUEUED_JOBS:
                return False
            future = self._executor.submit(self._run_one, job_id)
            self._in_flight[job_id] = future
            future.add_done_callback(lambda _: self._complete(job_id))
            return True

    async def start(self) -> int:
        if self._task is not None:
            return 0
        self._loop = asyncio.get_running_loop()
        recovered = await asyncio.to_thread(self._recover_stale)
        self._task = asyncio.create_task(self._run(), name="quick-durable-job-runtime")
        return recovered

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._closed.set()
        self._stop.set()
        self.wake()
        await task
        self._task = None
        self._loop = None
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def _run(self) -> None:
        while not self._stop.is_set():
            processed = 0
            try:
                await asyncio.to_thread(self._recover_stale)
                processed = await asyncio.to_thread(self._drain_ready)
            except Exception:
                _LOGGER.exception("durable job poller cycle failed")
            if processed:
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass

    def _recover_stale(self) -> int:
        with session_scope(self._app.state.session_factory) as database:
            return build_job_service(database, self._app).recover_stale()

    def _drain_ready(self) -> int:
        with self._lock:
            queued = len(self._in_flight)
        backlog = max(self._max_workers * 4, self._max_workers) - queued
        if backlog <= 0:
            return 0
        with session_scope(self._app.state.session_factory) as database:
            ready = build_job_service(database, self._app).ready(limit=backlog)
            job_ids = tuple(job.id for job in ready if job.status is JobStatus.PENDING)
        submitted = 0
        for job_id in job_ids:
            if self.submit(job_id):
                submitted += 1
        return submitted

    def _run_one(self, job_id: str) -> bool:
        worker_id = f"{self._worker_prefix}:{job_id}"[:128]
        return execute_durable_job(self._app, job_id, worker_id)

    def _complete(self, job_id: str) -> None:
        with self._lock:
            self._in_flight.pop(job_id, None)
        if not self._closed.is_set():
            self.wake()


async def start_job_runtime(app: FastAPI) -> int:
    runtime = DurableJobRuntime(app)
    app.state.job_runtime = runtime
    return await runtime.start()


async def stop_job_runtime(app: FastAPI) -> None:
    runtime = getattr(app.state, "job_runtime", None)
    if isinstance(runtime, DurableJobRuntime):
        await runtime.stop()


__all__ = ["start_job_runtime", "stop_job_runtime"]
