"""Bridge between the persisted model registry and the transport client.

The domain module owns the records; this module is the only place that turns
one into a live ``LlmConfig``, so the strict endpoint rules are enforced exactly
once, right before traffic leaves the process.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from xiaoying_quick.modules.data_sources.ports import SecretStore
from xiaoying_quick.modules.models import ModelConfigRecord, ModelConfigService
from xiaoying_quick.shared.model_endpoint import chat_completion_endpoint

from .client import ChatCompletionClient
from .config import LlmConfig
from .errors import LlmError

#: Thinking intensity → token budget handed to models that accept one.
THINKING_BUDGETS: dict[str, int] = {"low": 2_048, "medium": 8_192, "high": 32_768}


class ModelRegistry:
    def __init__(self, service: ModelConfigService, secrets: SecretStore) -> None:
        self._service = service
        self._secrets = secrets

    def service(self) -> ModelConfigService:
        return self._service

    def active_record(self) -> ModelConfigRecord | None:
        return self._service.active()

    def llm_config(self, record: ModelConfigRecord) -> LlmConfig:
        return LlmConfig(
            endpoint_url=chat_completion_endpoint(record.endpoint_url),
            api_key=self._secrets.get(record.secret_ref),
            model_id=record.model_id,
            timeout_seconds=record.timeout_seconds,
            temperature=record.temperature,
            max_tokens=record.max_tokens,
            reasoning=record.reasoning,  # type: ignore[arg-type]
        )

    def active_client(self) -> ChatCompletionClient | None:
        """A fresh client for the active configuration; None when nothing is active.

        Callers own the client lifecycle: durable jobs run one event loop per
        job, and the client rebinds itself to whatever loop is running.
        """

        record = self._service.active()
        if record is None:
            return None
        return ChatCompletionClient(self.llm_config(record))

    def client(
        self,
        config_id: str | None = None,
        *,
        thinking: str | None = None,
        thinking_level: str | None = None,
    ) -> ChatCompletionClient | None:
        """A client for one run: optional model pick plus thinking overrides.

        ``thinking`` is "on"/"off" (explicit user choice mapped to
        enable_thinking/thinking_budget) or None/"default" to keep the
        record's configured reasoning mode.
        """

        record: ModelConfigRecord | None = None
        if config_id:
            try:
                record = self._service.get(config_id)
            except Exception:  # noqa: BLE001 - fall back to the active record
                record = None
        if record is None:
            record = self._service.active()
        if record is None:
            return None
        config = self.llm_config(record)
        if thinking == "off":
            config = replace(config, reasoning="off", enable_thinking=False, thinking_budget=None)
        elif thinking == "on":
            config = replace(
                config,
                reasoning="on",
                enable_thinking=True,
                thinking_budget=THINKING_BUDGETS.get(thinking_level or "medium", 8_192),
            )
        return ChatCompletionClient(config)

    async def test(self, record: ModelConfigRecord) -> dict[str, Any]:
        """One cheap completion against the endpoint to prove it answers."""

        started = time.monotonic()
        client: ChatCompletionClient | None = None
        try:
            client = ChatCompletionClient(self.llm_config(record))
            completion = await client.complete_text(
                purpose="model.config_test",
                system_prompt="Reply with the single word: ok",
                user_prompt="ping",
                max_tokens=2_048,
            )
            return {
                "ok": True,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "model_id": record.model_id,
                "preview": completion.content.strip()[:120],
                "error": None,
            }
        except LlmError as exc:
            return {
                "ok": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "model_id": record.model_id,
                "preview": None,
                "error": f"{exc.code.value}: {exc.detail or exc}"[:300],
            }
        except ValueError as exc:
            return {
                "ok": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "model_id": record.model_id,
                "preview": None,
                "error": str(exc)[:300],
            }
        finally:
            if client is not None:
                await client.aclose()


__all__ = ["ModelRegistry"]
