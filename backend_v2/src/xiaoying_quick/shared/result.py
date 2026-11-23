"""Common cursor page contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CursorPage(Generic[T]):
    items: tuple[T, ...]
    next_cursor: int
    has_more: bool
