"""Pure domain boundary for generate-only Labs."""

from .contracts import (
    CandidateSQL,
    JSONScalar,
    LabContractError,
    LabContractErrorCode,
    LabRequest,
)
from .extractor import LabResponseExtractor
from .ports import LabPort, supports_controlled_prompt

__all__ = [
    "CandidateSQL",
    "JSONScalar",
    "LabContractError",
    "LabContractErrorCode",
    "LabPort",
    "LabRequest",
    "LabResponseExtractor",
    "supports_controlled_prompt",
]
