from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contracts import RecallHit, RecallReceipt, RecallRequest


class RecallSourcePort(Protocol):
    """Search adapter. The domain broker still enforces ACL and budgets on its output."""

    def search(
        self,
        request: RecallRequest,
        *,
        candidate_limit: int,
    ) -> Sequence[RecallHit]: ...


class RecallReceiptSink(Protocol):
    def append(self, receipt: RecallReceipt) -> None: ...
