"""Model adapters. Only this package may talk to a chat completion endpoint."""

from .client import (
    AssistantTurn,
    ChatCompletionClient,
    ChatTurn,
    Completion,
    ContentDelta,
    JsonCompletion,
    ReasoningDelta,
    StreamEvent,
    ToolCallFragment,
    TurnComplete,
)
from .config import LlmConfig
from .errors import LlmError, LlmErrorCode

__all__ = [
    "AssistantTurn",
    "ChatCompletionClient",
    "ChatTurn",
    "Completion",
    "ContentDelta",
    "JsonCompletion",
    "LlmConfig",
    "LlmError",
    "LlmErrorCode",
    "ReasoningDelta",
    "StreamEvent",
    "ToolCallFragment",
    "TurnComplete",
]
