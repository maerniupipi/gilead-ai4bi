"""Recall business terms through the AZAI agent query (查数) interface."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

from .azai_runner import AzaiQueryError, _parse_sse, _text_value

_OUTPUT_LIMIT = 12_000


def parse_bailian_recall_payload(payload: Mapping[str, Any]) -> dict[str, Any] | str:
    """Turn the SSE end-event into a knowledge object or raw text."""

    raw = _text_value(payload)
    if raw is None:
        return ""
    if isinstance(raw, Mapping):
        return dict(raw)
    if not isinstance(raw, str):
        return str(raw)
    stripped = raw.strip()
    if not stripped:
        return ""
    try:
        body = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(body, Mapping):
        return dict(body)
    return stripped


def format_bailian_knowledge(body: Mapping[str, Any] | str) -> str:
    """Render 知识词条 / NER first, then a compact 候选值 list."""

    if isinstance(body, str):
        return body.strip()[:_OUTPUT_LIMIT]
    if not body:
        return ""
    lines: list[str] = []
    terms = body.get("知识词条")
    if isinstance(terms, Mapping) and terms:
        lines.append("知识词条：")
        for key, value in terms.items():
            lines.append(f"- {key}：{value}")
        lines.append("")
    ner = body.get("NER")
    if isinstance(ner, Mapping) and ner:
        lines.append("NER：")
        for key, value in ner.items():
            lines.append(f"- {key}：{value}")
        lines.append("")
    candidates = body.get("候选值")
    if isinstance(candidates, Mapping) and candidates:
        lines.append("候选值：")
        for field, values in list(candidates.items())[:24]:
            if isinstance(values, (list, tuple)):
                shown = "、".join(str(item) for item in values[:8])
                extra = f" 等{len(values)}个" if len(values) > 8 else ""
                lines.append(f"- {field}：{shown}{extra}")
            else:
                lines.append(f"- {field}：{values}")
        lines.append("")
    rendered = "\n".join(lines).strip()
    if rendered:
        return rendered[:_OUTPUT_LIMIT]
    dumped = json.dumps(body, ensure_ascii=False, indent=2)
    return dumped[:_OUTPUT_LIMIT]


def _bearer(token: str) -> str:
    clean = token.strip()
    if clean.lower().startswith("bearer "):
        return clean
    return f"Bearer {clean}"


class BailianRecallRunner:
    """One recall = one AZAI session; message text is {query, lab_type}."""

    def __init__(
        self,
        *,
        create_session_url: str,
        run_url: str,
        agent_code: str,
        authorization: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._create_session_url = create_session_url
        self._run_url = run_url
        self._agent_code = agent_code
        self._authorization = _bearer(authorization)
        self._timeout_seconds = timeout_seconds

    def recall(self, query: str, lab_type: str) -> str:
        payload = self._run(query=query, lab_type=lab_type)
        body = parse_bailian_recall_payload(payload)
        return format_bailian_knowledge(body)

    def _run(self, *, query: str, lab_type: str) -> dict[str, Any]:
        headers = {
            "Authorization": self._authorization,
            "Content-Type": "application/json",
        }
        message_text = json.dumps(
            {"query": query, "lab_type": lab_type},
            ensure_ascii=False,
        )
        with httpx.Client(trust_env=False, follow_redirects=False) as client:
            created = client.post(
                self._create_session_url,
                headers=headers,
                json={"agentCode": self._agent_code},
                timeout=min(30.0, self._timeout_seconds),
            )
            created.raise_for_status()
            created_body = created.json()
            if not created_body.get("success"):
                raise AzaiQueryError(
                    f"百炼召回建会话失败：{created_body.get('errorMsg') or created_body.get('errorCode')}"
                )
            session_id = created_body["data"]["uniqueCode"]
            response = client.post(
                self._run_url,
                headers=headers,
                json={
                    "sessionId": session_id,
                    "message": {
                        "text": message_text,
                        "metadata": {"messages": []},
                    },
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        events = _parse_sse(response.content.decode("utf-8", errors="replace"))
        if not events:
            raise AzaiQueryError("百炼召回没有返回 SSE 事件")
        ended = next((item for item in reversed(events) if item.get("end")), events[-1])
        if not isinstance(ended, dict):
            raise AzaiQueryError("百炼召回结束事件不是对象")
        return ended
