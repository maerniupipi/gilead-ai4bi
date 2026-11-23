from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

REASONING_MODES = frozenset({"auto", "on", "off"})


@dataclass(frozen=True)
class ModelConfigRecord:
    """A selectable chat endpoint the agent loop may run against.

    The API key never lives here: only a reference into the secret store, so a
    database copy or an event payload cannot leak the credential.
    """

    id: str
    name: str
    endpoint_url: str
    model_id: str
    secret_ref: str
    temperature: float
    max_tokens: int
    reasoning: str
    timeout_seconds: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def to_public_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "endpoint_url": self.endpoint_url,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning": self.reasoning,
            "timeout_seconds": self.timeout_seconds,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
