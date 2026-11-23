"""Transport-independent contracts for the laboratory boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Union

from xiaoying_quick.shared.compat import StrEnum

JSONScalar = Union[str, int, float, bool, None]


class LabContractErrorCode(StrEnum):
    INVALID_RESPONSE = "invalid_response"
    MISSING_SQL_CITATIONS = "missing_sql_citations"
    INVALID_SQL_CITATIONS = "invalid_sql_citations"
    NO_VALID_SQL_CITATIONS = "no_valid_sql_citations"


class LabContractError(ValueError):
    """A Lab response could not be reduced to the trusted SQL-only contract."""

    def __init__(self, code: LabContractErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LabRequest:
    """The complete payload a Quick Lab adapter is allowed to receive.

    Credentials, raw chat history and arbitrary context are intentionally absent.
    ``session_params`` accepts scalar, allow-listed orchestration values only.
    """

    atom_id: str
    lab_id: str
    query: str
    controlled_prompt: str = ""
    session_params: Mapping[str, JSONScalar] = field(default_factory=dict)
    generate_only: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("atom_id", self.atom_id),
            ("lab_id", self.lab_id),
            ("query", self.query),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.controlled_prompt, str):
            raise TypeError("controlled_prompt must be a string")
        if not self.generate_only:
            raise ValueError("Quick Lab requests must use generate-only mode")

        forbidden_names = {
            "api_key",
            "authorization",
            "credential",
            "password",
            "refresh_token",
            "secret",
            "token",
        }
        forbidden_suffixes = (
            "_api_key",
            "_authorization",
            "_credential",
            "_password",
            "_refresh_token",
            "_secret",
            "_token",
        )
        clean_params: dict[str, JSONScalar] = {}
        for key, session_value in self.session_params.items():
            if not isinstance(key, str):
                raise TypeError("session parameter names must be strings")
            normalized_key = key.strip().casefold().replace("-", "_")
            if not normalized_key:
                raise ValueError("session parameter names must not be empty")
            compact_key = normalized_key.replace("_", "")
            if (
                normalized_key in forbidden_names
                or normalized_key.endswith(forbidden_suffixes)
                or compact_key.endswith(
                    (
                        "apikey",
                        "authorization",
                        "credential",
                        "password",
                        "refreshtoken",
                        "secret",
                        "token",
                    )
                )
            ):
                raise ValueError(f"sensitive session parameter is forbidden: {key}")
            if not isinstance(session_value, (str, int, float, bool)) and session_value is not None:
                raise TypeError(f"session parameter must be a JSON scalar: {key}")
            if isinstance(session_value, float) and not math.isfinite(session_value):
                raise ValueError(f"session parameter must be finite: {key}")
            clean_params[key] = session_value
        object.__setattr__(self, "session_params", MappingProxyType(clean_params))


@dataclass(frozen=True)
class CandidateSQL:
    """The only trusted projection of a Lab response.

    Both text fields come exclusively from one top-level ``sql_citations`` item.
    The raw Lab response is deliberately not retained on this object.
    """

    atom_id: str
    lab_id: str
    query: str
    sql: str
    candidate_no: int
    # Display-only Lab prose (理解 / 步骤 / 总结). Never used as a Fact.
    narrative: str = ""
    # The Lab's own trace/session id for the call, kept for source tracing.
    session_id: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("atom_id", self.atom_id),
            ("lab_id", self.lab_id),
            ("query", self.query),
            ("sql", self.sql),
        ):
            stripped = value.strip()
            if not stripped:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, stripped)
        object.__setattr__(self, "narrative", (self.narrative or "").strip()[:8_000])
        object.__setattr__(self, "session_id", (self.session_id or "").strip()[:128])
        if self.candidate_no < 0:
            raise ValueError("candidate_no must be non-negative")
