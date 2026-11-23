"""Run-level model selection and thinking overrides."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from xiaoying_quick.infrastructure.llm.config import LlmConfig
from xiaoying_quick.infrastructure.llm.registry import THINKING_BUDGETS, ModelRegistry
from xiaoying_quick.modules.models import ModelConfigRecord
from xiaoying_quick.shared.model_endpoint import chat_completion_endpoint


def _record(config_id: str = "model-1", model_id: str = "qwen3.7-max") -> ModelConfigRecord:
    return ModelConfigRecord(
        id=config_id,
        name="bailian",
        endpoint_url="https://llm.example/v1/chat/completions",
        model_id=model_id,
        secret_ref="secret-1",
        temperature=0.2,
        max_tokens=16_384,
        reasoning="off",
        timeout_seconds=180.0,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class _Service:
    def __init__(self, records: list[ModelConfigRecord]) -> None:
        self.records = records

    def get(self, config_id: str) -> ModelConfigRecord:
        for record in self.records:
            if record.id == config_id:
                return record
        raise KeyError(config_id)

    def active(self) -> ModelConfigRecord | None:
        return next((record for record in self.records if record.is_active), None)


class _Secrets:
    def get(self, ref: str) -> str:
        return f"key-for-{ref}"


def _registry(*records: ModelConfigRecord) -> ModelRegistry:
    return ModelRegistry(_Service(list(records)), _Secrets())


def test_config_enable_thinking_overrides_legacy_flag() -> None:
    config = LlmConfig(
        endpoint_url="https://llm.example/v1/chat/completions",
        api_key="k",
        model_id="qwen3.7-max",
        reasoning="on",
        enable_thinking=True,
        thinking_budget=2048,
    )
    assert config.request_overrides == {"enable_thinking": True, "thinking_budget": 2048}

    off = LlmConfig(
        endpoint_url="https://llm.example/v1/chat/completions",
        api_key="k",
        model_id="qwen3.7-max",
        reasoning="on",
        enable_thinking=False,
    )
    assert off.request_overrides == {"enable_thinking": False}


def test_client_picks_requested_model_and_applies_thinking() -> None:
    active = _record()
    other = _record(config_id="model-2", model_id="step-3.7-flash")
    registry = _registry(active, other)

    client = registry.client("model-2", thinking="on", thinking_level="high")
    assert client is not None
    config = client._config
    assert config.model_id == "step-3.7-flash"
    assert config.enable_thinking is True
    assert config.thinking_budget == THINKING_BUDGETS["high"]

    off_client = registry.client(None, thinking="off")
    assert off_client is not None
    assert off_client._config.model_id == "qwen3.7-max"
    assert off_client._config.enable_thinking is False
    assert off_client._config.request_overrides == {"enable_thinking": False}


def test_client_falls_back_to_active_on_unknown_id_and_default_thinking() -> None:
    registry = _registry(_record())

    fallback = registry.client("missing", thinking="default")
    assert fallback is not None and fallback._config.model_id == "qwen3.7-max"
    # No explicit choice: the record's configured reasoning flag applies.
    assert fallback._config.enable_thinking is None
    assert fallback._config.request_overrides == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize(
    ("base", "endpoint"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/chat/completions"),
        ("https://llm.example/v1/", "https://llm.example/v1/chat/completions"),
        ("https://llm.example/api/v3", "https://llm.example/api/v3/chat/completions"),
        ("https://llm.example/compatible-mode/v1", "https://llm.example/compatible-mode/v1/chat/completions"),
        ("https://llm.example/v1/chat/completions", "https://llm.example/v1/chat/completions"),
    ],
)
def test_stored_base_url_builds_the_chat_client(base: str, endpoint: str) -> None:
    record = replace(_record(), endpoint_url=base)
    client = _registry(record).active_client()
    assert client is not None
    assert client._config.endpoint_url == endpoint


@pytest.mark.parametrize("url", [
    "https://user:password@llm.example/v1", "https://llm.example/v1?key=private",
    "https://llm.example/v1#fragment", "http://remote.example/v1",
    "https://llm.example:bad/v1", "https://llm.example/responses",
])
def test_endpoint_normalization_preserves_transport_restrictions(url: str) -> None:
    with pytest.raises(ValueError):
        chat_completion_endpoint(url)


def test_model_test_returns_a_failure_when_client_configuration_is_invalid() -> None:
    record = replace(_record(), endpoint_url="https://llm.example/responses")
    result = asyncio.run(_registry(record).test(record))
    assert result["ok"] is False
    assert result["preview"] is None
    assert "地址" in result["error"]
