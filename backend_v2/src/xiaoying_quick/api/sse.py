"""Cursor-based server-sent event serialization and polling."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from xiaoying_quick.infrastructure.persistence.repositories.runs import SqlAlchemyRunRepository
from xiaoying_quick.infrastructure.persistence.session import SessionFactory
from xiaoying_quick.modules.runs.contracts import RunEvent


def encode_event(event: RunEvent) -> str:
    data = json.dumps(
        {
            "run_id": event.run_id,
            "cursor": event.cursor,
            "type": event.event_type,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {event.cursor}\nevent: {event.event_type}\ndata: {data}\n\n"


async def stream_events(
    *,
    session_factory: SessionFactory,
    run_id: str,
    after: int,
    follow: bool,
    poll_seconds: float,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    cursor = after
    last_write = time.monotonic()

    while True:
        page, run = await asyncio.to_thread(_read_event_page, session_factory, run_id, cursor)

        for event in page.items:
            cursor = event.cursor
            last_write = time.monotonic()
            yield encode_event(event)

        if page.has_more:
            continue
        if (
            not follow
            or run is None
            or (run.status.is_terminal and cursor >= run.next_event_cursor)
        ):
            return

        now = time.monotonic()
        if now - last_write >= heartbeat_seconds:
            last_write = now
            yield f": heartbeat {cursor}\n\n"
        await asyncio.sleep(poll_seconds)


def _read_event_page(session_factory: SessionFactory, run_id: str, after: int):
    with session_factory() as session:
        repository = SqlAlchemyRunRepository(session)
        return repository.list_events(run_id, after=after, limit=200), repository.get(run_id)
