"""Ports implemented by infrastructure health probes."""

from __future__ import annotations

from typing import Protocol

from .contracts import DependencyCheck


class DependencyProbe(Protocol):
    def check(self) -> tuple[DependencyCheck, ...]: ...
