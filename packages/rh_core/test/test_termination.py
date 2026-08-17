from __future__ import annotations

import pytest

from rh_core import TerminationReason, resolve_termination_reason


def test_no_candidate_resolves_to_none() -> None:
    assert resolve_termination_reason([]) is TerminationReason.NONE
    assert resolve_termination_reason([TerminationReason.NONE]) is TerminationReason.NONE


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        (TerminationReason.ENV_ERROR, TerminationReason.AGENT_ERROR),
        (TerminationReason.AGENT_ERROR, TerminationReason.FAILURE),
        (TerminationReason.FAILURE, TerminationReason.INVALID_TASK),
        (TerminationReason.INVALID_TASK, TerminationReason.ABORTED),
        (TerminationReason.ABORTED, TerminationReason.SUCCESS),
        (TerminationReason.SUCCESS, TerminationReason.TIMEOUT),
    ],
)
def test_priority_is_deterministic(
    higher: TerminationReason, lower: TerminationReason
) -> None:
    assert resolve_termination_reason([lower, higher]) is higher
    assert resolve_termination_reason([higher, lower]) is higher


def test_duplicate_candidates_do_not_change_result() -> None:
    assert resolve_termination_reason(
        [TerminationReason.TIMEOUT, TerminationReason.SUCCESS, TerminationReason.SUCCESS]
    ) is TerminationReason.SUCCESS


def test_raw_integer_candidate_is_rejected() -> None:
    with pytest.raises(TypeError, match="TerminationReason"):
        resolve_termination_reason([1])  # type: ignore[list-item]
