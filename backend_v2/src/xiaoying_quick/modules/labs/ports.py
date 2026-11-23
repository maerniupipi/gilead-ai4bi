"""Ports owned by the Lab domain."""

from __future__ import annotations

from typing import Protocol

from .contracts import CandidateSQL, LabRequest


class LabPort(Protocol):
    """Replaceable generate-only Lab client.

    HTTP details, authentication and retries belong to an infrastructure adapter.
    """

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]: ...


def supports_controlled_prompt(port: LabPort) -> bool:
    """Return only an explicitly declared Lab capability.

    The current laboratory HTTP contract accepts the atomic ``query`` only.
    Missing capability metadata therefore fails closed instead of making a
    second request whose repair instructions would be silently discarded.
    """

    return getattr(port, "supports_controlled_prompt", False) is True
