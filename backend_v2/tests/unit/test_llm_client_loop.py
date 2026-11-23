from __future__ import annotations

import asyncio

from xiaoying_quick.infrastructure.llm.client import ChatCompletionClient
from xiaoying_quick.infrastructure.llm.config import LlmConfig


def _config() -> LlmConfig:
    return LlmConfig(
        endpoint_url="https://example.test/v1/chat/completions",
        api_key="sk-test",
        model_id="test-model",
    )


async def _grab(client: ChatCompletionClient):
    return client._client_for_running_loop()


def test_owned_http_client_rebinds_after_asyncio_run_closes_loop() -> None:
    client = ChatCompletionClient(_config())
    first = asyncio.run(_grab(client))
    second = asyncio.run(_grab(client))
    try:
        assert first is not second
    finally:
        asyncio.run(client.aclose())
