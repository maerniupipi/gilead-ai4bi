"""HTTPX adapter for an OpenAI-protocol chat completion endpoint.

Every model-backed port in this backend talks through this one client, so the
transport, the size ceiling, and the failure vocabulary are defined once. The
client never retries and never substitutes a stand-in answer: a model problem
has to be visible while the system is being debugged internally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Union

import httpx

from .config import LlmConfig
from .context_window import ContextReading, prepare_context
from .token_count import PromptCounter
from .errors import LlmError, LlmErrorCode

_LOGGER = logging.getLogger(__name__)
_JSON_FENCE_PREFIXES = ("```json", "```JSON", "```")


@dataclass(frozen=True)
class Completion:
    """One model reply, with the model's own reasoning kept alongside it.

    A reasoning model writes its deliberation to a separate channel. That text
    is what the product shows as 思考过程, so it is carried through as a first
    class value rather than discarded at the transport boundary.
    """

    request_id: str
    content: str
    reasoning: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class JsonCompletion:
    request_id: str
    payload: dict[str, Any]
    reasoning: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallFragment:
    """One tool invocation the model requested, with JSON-encoded arguments."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ChatTurn:
    """One message in a multi-turn conversation handed to ``stream_chat``.

    Roles follow the OpenAI chat vocabulary: ``system``, ``user``,
    ``assistant`` (optionally carrying ``tool_calls``), and ``tool`` (a tool
    result bound to its call through ``tool_call_id``).
    """

    role: str
    content: str = ""
    reasoning: str = ""
    tool_calls: tuple[ToolCallFragment, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class AssistantTurn:
    """The model's complete reply for one step of the agent loop."""

    content: str
    reasoning: str
    tool_calls: tuple[ToolCallFragment, ...]
    finish_reason: str
    usage: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class TurnComplete:
    turn: AssistantTurn


StreamEvent = Union[ContentDelta, ReasoningDelta, TurnComplete]


class ChatCompletionClient:
    """Send one prompt, return the assistant text or its parsed JSON body."""

    def __init__(
        self,
        config: LlmConfig,
        *,
        client: httpx.AsyncClient | None = None,
        request_id_factory: Callable[[], str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        # ``trust_env`` stays on: outbound model traffic is expected to follow
        # the operator's proxy configuration.
        # Durable jobs run inside ``asyncio.run()``, which opens and closes a
        # fresh loop per job. An httpx client bound to a dead loop raises
        # ``Event loop is closed`` on the next call, so a process-wide client
        # must rebind itself when the loop changes.
        self._injected_client = client
        self._client = client
        self._owns_client = client is None
        self._bound_loop: asyncio.AbstractEventLoop | None = None
        self._request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        self._logger = logger or _LOGGER
        self._closed = False

    @property
    def model_id(self) -> str:
        return self._config.model_id

    async def complete_json(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> JsonCompletion:
        """Return the assistant message parsed as a JSON object."""

        completion = await self._complete(
            purpose=purpose,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_object=True,
            max_tokens=max_tokens,
        )
        payload: object
        try:
            payload = json.loads(_strip_json_fence(completion.content))
        except (json.JSONDecodeError, ValueError) as error:
            raise LlmError(
                LlmErrorCode.INVALID_JSON,
                purpose=purpose,
                request_id=completion.request_id,
                detail=_preview(completion.content),
            ) from error
        if not isinstance(payload, Mapping):
            raise LlmError(
                LlmErrorCode.INVALID_PAYLOAD,
                purpose=purpose,
                request_id=completion.request_id,
                detail="model returned a non-object json body",
            )
        return JsonCompletion(
            request_id=completion.request_id,
            payload=dict(payload),
            reasoning=completion.reasoning,
            usage=completion.usage,
        )

    async def complete_text(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        json_object: bool = False,
        max_tokens: int | None = None,
    ) -> Completion:
        return await self._complete(
            purpose=purpose,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_object=json_object,
            max_tokens=max_tokens,
        )

    def context_body(self, messages, tools, max_tokens=None):
        body = {
            "model": self._config.model_id,
            "messages": [_serialize_turn(turn) for turn in messages],
            "max_tokens": max_tokens or self._config.max_tokens,
            **self._config.request_overrides,
        }
        if tools:
            body["tools"] = [dict(tool) for tool in tools]
            body["tool_choice"] = "auto"
        return body

    def output_size(self, text):
        return PromptCounter({"model": self._config.model_id}).text_size(text)

    async def stream_chat(
        self,
        *,
        purpose: str,
        messages: Sequence[ChatTurn],
        tools: Sequence[Mapping[str, Any]] | None = None,
        max_tokens: int | None = None,
        on_context: Callable[[ContextReading, list], None] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream one multi-turn, tool-enabled completion.

        Yields ``ContentDelta`` / ``ReasoningDelta`` as the model writes, then
        one ``TurnComplete`` carrying the assembled reply. The iterator owns the
        HTTP response: exhausting it (or closing it) releases the connection.
        """

        request_id = self._new_request_id()
        if self._closed:
            raise LlmError(LlmErrorCode.CLOSED, purpose=purpose, request_id=request_id)
        if not messages:
            raise LlmError(
                LlmErrorCode.INVALID_REQUEST,
                purpose=purpose,
                request_id=request_id,
                detail="stream_chat requires at least one message",
            )
        http_client = self._client_for_running_loop()

        body = {
            "stream": True, "stream_options": {"include_usage": True},
            "temperature": self._config.temperature,
            **self.context_body(messages, tools, max_tokens),
        }
        from ..monthly_quota import capacity
        reading = prepare_context(body)
        if on_context is not None:
            on_context(reading, body["messages"])
        input_cost = reading.reserved_input
        with capacity(input_cost, body["max_tokens"]) as permitted:
            body["max_tokens"] = permitted
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            calls: dict[int, dict[str, str]] = {}
            finish_reason = ""
            usage: dict[str, int] = {}

            try:
                async with http_client.stream(
                    "POST",
                    self._config.endpoint_url,
                    headers={
                        "Accept": "text/event-stream",
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._config.api_key}",
                        "X-Request-ID": request_id,
                    },
                    json=body,
                    timeout=self._config.timeout_seconds,
                ) as response:
                    status_failure = _classify_status(response.status_code)
                    if status_failure is not None:
                        detail = ""
                        try:
                            raw = await response.aread()
                            detail = _preview(raw.decode("utf-8", errors="replace"))
                        except httpx.HTTPError:
                            pass
                        code, retryable = status_failure
                        raise LlmError(
                            code,
                            purpose=purpose,
                            request_id=request_id,
                            retryable=retryable,
                            status_code=response.status_code,
                            detail=detail,
                        )
                    async for line in response.aiter_lines():
                        stripped = line.strip()
                        if not stripped.startswith("data:"):
                            continue
                        data = stripped[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                            continue
                        if not isinstance(chunk, Mapping):
                            continue
                        chunk_usage = _usage(chunk)
                        if chunk_usage:
                            usage.update(chunk_usage)
                        choices = chunk.get("choices")
                        if not isinstance(choices, Sequence) or not choices:
                            continue
                        first = choices[0]
                        if not isinstance(first, Mapping):
                            continue
                        if first.get("finish_reason"):
                            finish_reason = str(first["finish_reason"])
                        delta = first.get("delta")
                        if not isinstance(delta, Mapping):
                            continue
                        text = _string(delta.get("content"))
                        if text:
                            content_parts.append(text)
                            yield ContentDelta(text=text)
                        thought = _string(delta.get("reasoning_content"))
                        if thought:
                            reasoning_parts.append(thought)
                            yield ReasoningDelta(text=thought)
                        for fragment in _delta_tool_calls(delta.get("tool_calls")):
                            slot = calls.setdefault(
                                fragment[0], {"id": "", "name": "", "arguments": ""}
                            )
                            if fragment[1]:
                                slot["id"] = fragment[1]
                            if fragment[2]:
                                slot["name"] = fragment[2]
                            slot["arguments"] += fragment[3]
            except httpx.TimeoutException as error:
                raise LlmError(
                    LlmErrorCode.TIMEOUT, purpose=purpose, request_id=request_id, retryable=True
                ) from error
            except LlmError:
                raise
            except Exception as error:
                raise LlmError(
                    LlmErrorCode.NETWORK_ERROR, purpose=purpose, request_id=request_id, retryable=True
                ) from error

            tool_calls = tuple(
                ToolCallFragment(
                    id=slot["id"] or f"call_{request_id}_{index}",
                    name=slot["name"],
                    arguments=slot["arguments"] or "{}",
                )
                for index, slot in sorted(calls.items())
                if slot["name"]
            )
            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts)
            if finish_reason == "length" and not content and not tool_calls:
                raise LlmError(
                    LlmErrorCode.TRUNCATED,
                    purpose=purpose,
                    request_id=request_id,
                    detail=(
                        f"model hit the {max_tokens or self._config.max_tokens} token ceiling "
                        f"after {usage.get('reasoning_tokens', 0)} reasoning tokens"
                    ),
                )
            if not content and not tool_calls:
                raise LlmError(
                    LlmErrorCode.EMPTY_COMPLETION,
                    purpose=purpose,
                    request_id=request_id,
                    detail=f"finish_reason={finish_reason or 'unknown'}",
                )
            self._logger.info(
                "model stream completed",
                extra={
                    "llm_request_id": request_id,
                    "llm_purpose": purpose,
                    "llm_model": self._config.model_id,
                    "llm_usage": usage,
                    "llm_tool_calls": len(tool_calls),
                },
            )
            _meter_usage(
                purpose=purpose,
                model_id=self._config.model_id,
                request_id=request_id,
                usage=usage,
            )
            yield TurnComplete(
                turn=AssistantTurn(
                    content=content,
                    reasoning=reasoning,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                    usage=usage,
                )
            )

    async def _complete(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        json_object: bool,
        max_tokens: int | None,
    ) -> Completion:
        """Issue one call.

        The request id belongs to this call, not to the client: concurrent
        calls share one client, and an error has to name the request that
        actually failed.
        """

        request_id = self._new_request_id()
        if self._closed:
            raise LlmError(LlmErrorCode.CLOSED, purpose=purpose, request_id=request_id)
        http_client = self._client_for_running_loop()

        body: dict[str, Any] = {
            "model": self._config.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": self._config.temperature,
            "max_tokens": max_tokens or self._config.max_tokens,
            **self._config.request_overrides,
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        from ..monthly_quota import capacity
        input_cost = prepare_context(body).reserved_input
        with capacity(input_cost, body["max_tokens"]) as permitted:
            body["max_tokens"] = permitted
            try:
                outbound = http_client.build_request(
                    "POST",
                    self._config.endpoint_url,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._config.api_key}",
                        "X-Request-ID": request_id,
                    },
                    json=body,
                    timeout=self._config.timeout_seconds,
                )
            except (TypeError, ValueError, httpx.HTTPError) as error:
                raise LlmError(
                    LlmErrorCode.INVALID_REQUEST, purpose=purpose, request_id=request_id
                ) from error

            try:
                response = await http_client.send(outbound, follow_redirects=False)
            except httpx.TimeoutException as error:
                raise LlmError(
                    LlmErrorCode.TIMEOUT, purpose=purpose, request_id=request_id, retryable=True
                ) from error
            except Exception as error:
                raise LlmError(
                    LlmErrorCode.NETWORK_ERROR, purpose=purpose, request_id=request_id, retryable=True
                ) from error

            try:
                status_failure = _classify_status(response.status_code)
                if status_failure is not None:
                    code, retryable = status_failure
                    raise LlmError(
                        code,
                        purpose=purpose,
                        request_id=request_id,
                        retryable=retryable,
                        status_code=response.status_code,
                        detail=_preview(response.text),
                    )
                raw = response.content
                if len(raw) > self._config.max_response_bytes:
                    raise LlmError(
                        LlmErrorCode.RESPONSE_TOO_LARGE,
                        purpose=purpose,
                        request_id=request_id,
                        status_code=response.status_code,
                    )
                try:
                    document = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                    raise LlmError(
                        LlmErrorCode.INVALID_JSON,
                        purpose=purpose,
                        request_id=request_id,
                        status_code=response.status_code,
                    ) from error
            finally:
                await response.aclose()

            message = _extract_message(document)
            usage = _usage(document)
            if message.finish_reason == "length":
                # A reasoning model spends max_tokens on its own deliberation first.
                # Say that plainly instead of reporting an empty answer: the fix is
                # a bigger budget, not a different prompt.
                raise LlmError(
                    LlmErrorCode.TRUNCATED,
                    purpose=purpose,
                    request_id=request_id,
                    status_code=response.status_code,
                    detail=(
                        f"model hit the {max_tokens or self._config.max_tokens} token ceiling "
                        f"after {usage.get('reasoning_tokens', 0)} reasoning tokens"
                    ),
                )
            if not message.content:
                raise LlmError(
                    LlmErrorCode.EMPTY_COMPLETION,
                    purpose=purpose,
                    request_id=request_id,
                    status_code=response.status_code,
                    detail=f"finish_reason={message.finish_reason or 'unknown'}",
                )

            self._logger.info(
                "model call completed",
                extra={
                    "llm_request_id": request_id,
                    "llm_purpose": purpose,
                    "llm_model": self._config.model_id,
                    "llm_usage": usage,
                },
            )
            _meter_usage(
                purpose=purpose,
                model_id=self._config.model_id,
                request_id=request_id,
                usage=usage,
            )
            return Completion(
                request_id=request_id,
                content=message.content,
                reasoning=message.reasoning,
                usage=usage,
            )

    def _client_for_running_loop(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return self._injected_client
        loop = asyncio.get_running_loop()
        if self._client is not None and self._bound_loop is loop and not loop.is_closed():
            return self._client
        # The previous loop is already closed; dropping the client is enough.
        self._client = httpx.AsyncClient(follow_redirects=False)
        self._bound_loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client and self._client is not None:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass
        self._client = None
        self._bound_loop = None

    async def __aenter__(self) -> ChatCompletionClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _new_request_id(self) -> str:
        try:
            candidate = self._request_id_factory()
        except Exception:
            return uuid.uuid4().hex
        return candidate if isinstance(candidate, str) and candidate.strip() else uuid.uuid4().hex


def _classify_status(status_code: int) -> tuple[LlmErrorCode, bool] | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 408:
        return LlmErrorCode.TIMEOUT, True
    if status_code == 429:
        return LlmErrorCode.RATE_LIMITED, True
    if 400 <= status_code < 500:
        return LlmErrorCode.HTTP_CLIENT_ERROR, False
    if 500 <= status_code < 600:
        return LlmErrorCode.HTTP_SERVER_ERROR, True
    return LlmErrorCode.UNEXPECTED_STATUS, False


@dataclass(frozen=True)
class _Message:
    content: str = ""
    reasoning: str = ""
    finish_reason: str = ""


def _extract_message(document: object) -> _Message:
    if not isinstance(document, Mapping):
        return _Message()
    choices = document.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        return _Message()
    first = choices[0]
    if not isinstance(first, Mapping):
        return _Message()
    finish_reason = first.get("finish_reason")
    message = first.get("message")
    if not isinstance(message, Mapping):
        return _Message(finish_reason=_string(finish_reason))
    return _Message(
        content=_string(message.get("content")),
        reasoning=_string(message.get("reasoning_content")),
        finish_reason=_string(finish_reason),
    )


def _usage(document: object) -> dict[str, int]:
    if not isinstance(document, Mapping):
        return {}
    usage = document.get("usage")
    if not isinstance(usage, Mapping):
        return {}
    counters = {
        key: int(value)
        for key, value in usage.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    details = usage.get("completion_tokens_details")
    if isinstance(details, Mapping):
        counters.update(
            {
                key: int(value)
                for key, value in details.items()
                if isinstance(key, str) and isinstance(value, int)
            }
        )
    return counters


def _string(raw: object) -> str:
    # No stripping: streaming deltas are concatenated verbatim, and trimming
    # each delta would eat the whitespace between tokens (e.g. tool-call
    # argument fragments like '"SELECT "' + '"SUM(...)"').
    return raw if isinstance(raw, str) else ""


def _strip_json_fence(text: str) -> str:
    """Tolerate a fenced block around an otherwise valid JSON object."""

    stripped = text.strip()
    for prefix in _JSON_FENCE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
            if stripped.endswith("```"):
                stripped = stripped[: -len("```")].strip()
            break
    return stripped


def _preview(text: str, limit: int = 240) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit]


def _meter_usage(
    *,
    purpose: str,
    model_id: str,
    request_id: str,
    usage: Mapping[str, Any] | None,
    status: str = "ok",
    error_code: str | None = None,
) -> None:
    try:
        from xiaoying_quick.modules.usage import record_llm_usage

        record_llm_usage(
            purpose=purpose,
            model_id=model_id,
            request_id=request_id,
            usage=usage,
            status=status,
            error_code=error_code,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.warning("usage metering hook failed purpose=%s", purpose, exc_info=True)


def _serialize_turn(turn: ChatTurn) -> dict[str, Any]:
    if turn.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": turn.tool_call_id,
            "content": turn.content,
        }
    if turn.role == "assistant":
        message: dict[str, Any] = {"role": "assistant", "content": turn.content or None}
        if turn.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in turn.tool_calls
            ]
        return message
    return {"role": turn.role, "content": turn.content}


def _delta_tool_calls(raw: object) -> tuple[tuple[int, str, str, str], ...]:
    """Normalize one streaming tool_calls fragment into (index, id, name, args)."""

    if not isinstance(raw, (list, tuple)):
        return ()
    fragments: list[tuple[int, str, str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            index = int(item.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        call_id = _string(item.get("id"))
        function = item.get("function")
        name = ""
        arguments = ""
        if isinstance(function, Mapping):
            name = _string(function.get("name"))
            arguments = _string(function.get("arguments"))
        fragments.append((index, call_id, name, arguments))
    return tuple(fragments)


__all__ = [
    "AssistantTurn",
    "ChatCompletionClient",
    "ChatTurn",
    "Completion",
    "ContentDelta",
    "JsonCompletion",
    "ReasoningDelta",
    "StreamEvent",
    "ToolCallFragment",
    "TurnComplete",
]
