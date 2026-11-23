"""Dependency-aware readiness aggregation."""

from __future__ import annotations

from .contracts import DependencyCheck, DependencyStatus, ReadinessReport
from .ports import DependencyProbe


class ReadinessService:
    def __init__(self, probe: DependencyProbe) -> None:
        self._probe = probe

    def report(self) -> ReadinessReport:
        try:
            checks = self._probe.check()
        except Exception:
            # A readiness endpoint must fail closed without reflecting driver,
            # endpoint, SQL, or credential details into an unauthenticated response.
            checks = (
                DependencyCheck(
                    name="application_database",
                    status=DependencyStatus.ERROR,
                    critical=True,
                    mode="connectivity",
                    detail="probe_failed",
                ),
            )
        return ReadinessReport(checks=checks)
