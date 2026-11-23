"""Context-bound LLM usage recorder (user + event + run)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from xiaoying_quick.shared.ids import new_id

_LOGGER = logging.getLogger(__name__)

UsageSink = Callable[[Mapping[str, Any]], None]


@dataclass(frozen=True)
class UsageAttribution:
    user_id: str
    username: str = ""
    display_name: str = ""
    run_id: str | None = None
    session_id: str | None = None
    mode: str = "normal"
    # 问数：用户原问题；洞察：父 run 上的用户原始问题
    question: str = ""


_attribution: ContextVar[UsageAttribution | None] = ContextVar(
    "usage_attribution", default=None
)
_usage_sink: UsageSink | None = None


def configure_usage_meter(sink: UsageSink | None) -> None:
    global _usage_sink
    _usage_sink = sink


@contextmanager
def bind_usage_attribution(attribution: UsageAttribution) -> Iterator[UsageAttribution]:
    token = _attribution.set(attribution)
    try:
        yield attribution
    finally:
        _attribution.reset(token)


def current_attribution() -> UsageAttribution | None:
    return _attribution.get()


def record_llm_usage(
    *,
    purpose: str,
    model_id: str,
    request_id: str = "",
    usage: Mapping[str, Any] | None = None,
    status: str = "ok",
    error_code: str | None = None,
    note: str | None = None,
) -> None:
    """Persist one LLM call. Never raises into the model path."""

    sink = _usage_sink
    if sink is None:
        return
    attr = _attribution.get()
    if attr is None or not attr.user_id:
        # System / unattributed probes (e.g. model.config_test) stay out of the ledger.
        return
    counters = usage or {}
    prompt = _int(counters.get("prompt_tokens"))
    completion = _int(counters.get("completion_tokens"))
    reasoning = _int(
        counters.get("reasoning_tokens")
        or counters.get("reasoning_completion_tokens")
        or 0
    )
    total = _int(counters.get("total_tokens"))
    if total <= 0:
        total = prompt + completion + reasoning
    try:
        sink({
            "id": new_id("usage"),
            "user_id": attr.user_id,
            "username": (attr.username or "")[:64],
            "display_name": (attr.display_name or attr.username or "")[:128],
            "run_id": attr.run_id,
            "session_id": attr.session_id,
            "mode": (attr.mode or "normal")[:16],
            "purpose": (purpose or "unknown")[:96],
            "question": (attr.question or "")[:4000],
            "model_id": (model_id or "")[:128],
            "request_id": (request_id or "")[:64],
            "status": (status or "ok")[:16],
            "error_code": error_code or None,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "total_tokens": total,
            "note": note[:500] if note else None,
        })
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "usage meter write failed purpose=%s user=%s",
            purpose,
            attr.user_id,
            exc_info=True,
        )


def _int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
