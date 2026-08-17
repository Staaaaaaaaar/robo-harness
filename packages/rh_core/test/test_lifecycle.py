from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from rh_core import (
    EpisodeLifecycle,
    EpisodeState,
    ErrorCode,
    ExperimentLifecycle,
    ExperimentState,
    LifecycleError,
    TerminationReason,
)


def assert_error_code(caught: pytest.ExceptionInfo[LifecycleError], code: ErrorCode) -> None:
    assert caught.value.issues[0].code is code


def test_experiment_happy_path() -> None:
    lifecycle = ExperimentLifecycle()
    for target in (
        ExperimentState.STARTING,
        ExperimentState.RUNNING,
        ExperimentState.FINALIZING,
        ExperimentState.FINISHED,
    ):
        lifecycle = lifecycle.transition(target)
    assert lifecycle.state is ExperimentState.FINISHED


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (ExperimentState.CREATED, ExperimentState.RUNNING),
        (ExperimentState.STARTING, ExperimentState.FINISHED),
        (ExperimentState.RUNNING, ExperimentState.FINISHED),
        (ExperimentState.FINALIZING, ExperimentState.RUNNING),
        (ExperimentState.FINISHED, ExperimentState.STARTING),
        (ExperimentState.FAILED, ExperimentState.STARTING),
    ],
)
def test_illegal_experiment_transitions_are_rejected(
    initial: ExperimentState, target: ExperimentState
) -> None:
    with pytest.raises(LifecycleError) as caught:
        ExperimentLifecycle(initial).transition(target)
    assert_error_code(caught, ErrorCode.INVALID_TRANSITION)


@pytest.mark.parametrize(
    "initial",
    [ExperimentState.STARTING, ExperimentState.RUNNING, ExperimentState.FINALIZING],
)
def test_active_experiment_can_fail(initial: ExperimentState) -> None:
    lifecycle = ExperimentLifecycle(initial).transition(ExperimentState.FAILED)
    assert lifecycle.state is ExperimentState.FAILED


def test_episode_happy_path_increments_sequence() -> None:
    lifecycle = EpisodeLifecycle("0000")
    lifecycle = lifecycle.transition(EpisodeState.READY)
    lifecycle = lifecycle.transition(EpisodeState.RUNNING)
    lifecycle = lifecycle.transition(
        EpisodeState.TERMINATING,
        termination_reason=TerminationReason.SUCCESS,
    )
    lifecycle = lifecycle.transition(EpisodeState.FINISHED)

    assert lifecycle.sequence == 4
    assert lifecycle.state is EpisodeState.FINISHED
    assert lifecycle.termination_reason is TerminationReason.SUCCESS


@pytest.mark.parametrize("initial", [EpisodeState.PREPARING, EpisodeState.READY])
def test_episode_can_terminate_before_running(initial: EpisodeState) -> None:
    lifecycle = EpisodeLifecycle("0000", state=initial)
    lifecycle = lifecycle.transition(
        EpisodeState.TERMINATING,
        termination_reason=TerminationReason.INVALID_TASK,
    )
    assert lifecycle.termination_reason is TerminationReason.INVALID_TASK


def test_entering_terminating_requires_reason() -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000", state=EpisodeState.RUNNING).transition(
            EpisodeState.TERMINATING
        )
    assert_error_code(caught, ErrorCode.TERMINATION_REQUIRED)


def test_reason_cannot_be_committed_before_terminating() -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000").transition(
            EpisodeState.READY,
            termination_reason=TerminationReason.SUCCESS,
        )
    assert_error_code(caught, ErrorCode.UNEXPECTED_TERMINATION_REASON)


def test_reason_cannot_be_committed_twice() -> None:
    lifecycle = EpisodeLifecycle("0000", state=EpisodeState.RUNNING).transition(
        EpisodeState.TERMINATING,
        termination_reason=TerminationReason.TIMEOUT,
    )
    with pytest.raises(LifecycleError) as caught:
        lifecycle.transition(
            EpisodeState.FINISHED,
            termination_reason=TerminationReason.SUCCESS,
        )
    assert_error_code(caught, ErrorCode.TERMINATION_ALREADY_COMMITTED)


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (EpisodeState.PREPARING, EpisodeState.RUNNING),
        (EpisodeState.READY, EpisodeState.FINISHED),
        (EpisodeState.RUNNING, EpisodeState.READY),
        (EpisodeState.TERMINATING, EpisodeState.RUNNING),
        (EpisodeState.FINISHED, EpisodeState.PREPARING),
    ],
)
def test_illegal_episode_transitions_are_rejected(
    initial: EpisodeState, target: EpisodeState
) -> None:
    reason = (
        TerminationReason.FAILURE
        if initial in {EpisodeState.TERMINATING, EpisodeState.FINISHED}
        else TerminationReason.NONE
    )
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000", state=initial, termination_reason=reason).transition(target)
    assert_error_code(caught, ErrorCode.INVALID_TRANSITION)


def test_lifecycle_snapshots_are_immutable() -> None:
    lifecycle = EpisodeLifecycle("0000")
    with pytest.raises(FrozenInstanceError):
        lifecycle.sequence = 2  # type: ignore[misc]


def test_raw_integer_target_is_rejected() -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000").transition(1)  # type: ignore[arg-type]
    assert_error_code(caught, ErrorCode.TYPE_MISMATCH)


@pytest.mark.parametrize("state", [EpisodeState.TERMINATING, EpisodeState.FINISHED])
def test_terminal_snapshot_requires_reason(state: EpisodeState) -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000", state=state)
    assert_error_code(caught, ErrorCode.TERMINATION_REQUIRED)


def test_non_terminal_snapshot_rejects_committed_reason() -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000", termination_reason=TerminationReason.SUCCESS)
    assert_error_code(caught, ErrorCode.UNEXPECTED_TERMINATION_REASON)


@pytest.mark.parametrize("sequence", [-1, 2**64, True, 1.5])
def test_sequence_must_be_uint64(sequence: object) -> None:
    with pytest.raises(LifecycleError) as caught:
        EpisodeLifecycle("0000", sequence=sequence)  # type: ignore[arg-type]
    issue = caught.value.issues[0]
    assert issue.code in {ErrorCode.TYPE_MISMATCH, ErrorCode.INVALID_VALUE}


def test_sequence_cannot_overflow() -> None:
    lifecycle = EpisodeLifecycle("0000", sequence=2**64 - 1)
    with pytest.raises(LifecycleError) as caught:
        lifecycle.transition(EpisodeState.READY)
    assert_error_code(caught, ErrorCode.INVALID_VALUE)
