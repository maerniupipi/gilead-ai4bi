"""Opaque identifier helpers."""

from __future__ import annotations

import re
import uuid

_PREFIX = re.compile(r"^[a-z][a-z0-9_]{1,15}$")


def new_id(prefix: str) -> str:
    if not _PREFIX.fullmatch(prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex}"
