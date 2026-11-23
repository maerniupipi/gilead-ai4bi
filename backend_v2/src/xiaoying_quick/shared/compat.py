"""Python 3.9 stand-ins for newer stdlib APIs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum


class StrEnum(str, Enum):
    """Minimal ``enum.StrEnum`` replacement for Python 3.9."""

    def __str__(self) -> str:
        return str(self.value)


def parse_iso_datetime(value: str) -> datetime:
    """Parse ISO-8601 datetimes, including the ``Z`` suffix rejected by 3.9."""

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
