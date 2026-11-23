"""Execute approved SQL through the AZAI agent query interface."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx

from xiaoying_quick.modules.data_sources import DataSourceRevision


class AzaiQueryError(RuntimeError):
    pass


def parse_azai_query_payload(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    """Turn the agent SSE end-event into columns and rows."""

    raw = _text_value(payload)
    body: Any = raw
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return (), ()
        try:
            body = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AzaiQueryError("AZAI query payload is not JSON") from exc
    if not isinstance(body, Mapping):
        raise AzaiQueryError("AZAI query payload must be an object")
    code = body.get("code", 200)
    if code not in (200, "200", None):
        raise AzaiQueryError(f"AZAI query failed: {body.get('msg') or code}")
    rows_obj = body.get("data", ())
    if rows_obj is None:
        return (), ()
    if not isinstance(rows_obj, (list, tuple)):
        raise AzaiQueryError("AZAI query data must be a list")
    if not rows_obj:
        return (), ()
    first = rows_obj[0]
    if isinstance(first, Mapping):
        columns = tuple(str(key) for key in first.keys())
        rows = tuple(
            tuple(_cell(row.get(column)) for column in columns)
            for row in rows_obj
            if isinstance(row, Mapping)
        )
        return columns, rows
    if isinstance(first, (list, tuple)):
        width = len(first)
        columns = tuple(f"c{index}" for index in range(width))
        rows = tuple(tuple(_cell(value) for value in row[:width]) for row in rows_obj)
        return columns, rows
    raise AzaiQueryError("AZAI query rows must be objects or arrays")


def _text_value(payload: Mapping[str, Any]) -> Any:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)) and content:
        first = content[0]
        if isinstance(first, str):
            return first
        if isinstance(first, Mapping):
            text = first.get("text")
            if isinstance(text, Mapping):
                return text.get("value")
            if text is not None:
                return text
            return first.get("value")
    if "data" in payload:
        return payload
    raise AzaiQueryError("AZAI query event has no text payload")


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AzaiSqlRunner:
    """Read-only runner: POST the SQL as the agent message text."""

    def __init__(
        self,
        *,
        create_session_url: str,
        run_url: str,
        agent_code: str,
        agent_version: str,
        authorization: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._create_session_url = create_session_url
        self._run_url = run_url
        self._agent_code = agent_code
        self._agent_version = agent_version
        self._authorization = authorization
        self._timeout_seconds = timeout_seconds

    def execute(
        self,
        *,
        revision: DataSourceRevision,
        password: str | None,
        sql: str,
        max_rows: int,
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...], bool, int]:
        del revision, password
        started = time.perf_counter()
        payload = self._run(sql)
        columns, rows = parse_azai_query_payload(payload)
        truncated = len(rows) > max_rows
        return columns, rows[:max_rows], truncated, int((time.perf_counter() - started) * 1000)

    def _run(self, sql: str) -> dict[str, Any]:
        headers = {
            "Authorization": self._authorization,
            "Content-Type": "application/json",
        }
        with httpx.Client(trust_env=False, follow_redirects=False) as client:
            created = client.post(
                self._create_session_url,
                headers=headers,
                json={"agentCode": self._agent_code, "agentVersion": self._agent_version},
                timeout=min(30.0, self._timeout_seconds),
            )
            created.raise_for_status()
            session_id = created.json()["data"]["uniqueCode"]
            response = client.post(
                self._run_url,
                headers=headers,
                json={
                    "sessionId": session_id,
                    "message": {"text": sql, "metadata": {"messages": []}},
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        events = _parse_sse(response.content.decode("utf-8", errors="replace"))
        if not events:
            raise AzaiQueryError("AZAI query returned no SSE events")
        ended = next((item for item in reversed(events) if item.get("end")), events[-1])
        if not isinstance(ended, dict):
            raise AzaiQueryError("AZAI query end event is not an object")
        return ended


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        try:
            payload = json.loads(stripped[5:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events
