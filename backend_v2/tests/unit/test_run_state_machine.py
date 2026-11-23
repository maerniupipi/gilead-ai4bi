"""Run state transition tests."""

import pytest

from xiaoying_quick.modules.runs.contracts import RunStatus
from xiaoying_quick.modules.runs.state_machine import validate_transition
from xiaoying_quick.shared.errors import InvalidTransition


def test_waiting_clarification_can_resume_running() -> None:
    validate_transition(RunStatus.RUNNING, RunStatus.WAITING_CLARIFICATION)
    validate_transition(RunStatus.WAITING_CLARIFICATION, RunStatus.RUNNING)


@pytest.mark.parametrize(
    "terminal",
    [RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED],
)
def test_terminal_states_cannot_transition(terminal: RunStatus) -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(terminal, RunStatus.RUNNING)
