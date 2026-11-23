"""Framework-independent health contracts."""

from __future__ import annotations

from dataclasses import dataclass

from xiaoying_quick.shared.compat import StrEnum


class DependencyStatus(StrEnum):
    """Finite, safe-to-expose dependency states."""

    OK = "ok"
    ERROR = "error"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DependencyCheck:
    """One dependency observation with no endpoint or credential material."""

    name: str
    status: DependencyStatus
    critical: bool
    mode: str
    detail: str

    @property
    def is_healthy(self) -> bool:
        return not self.critical or self.status in {
            DependencyStatus.OK,
            DependencyStatus.CONFIGURED,
        }

    def to_record(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "status": self.status.value,
            "critical": self.critical,
            "mode": self.mode,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate readiness based only on critical dependencies."""

    checks: tuple[DependencyCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.is_healthy for check in self.checks)

    def to_record(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "dependencies": [check.to_record() for check in self.checks],
        }
