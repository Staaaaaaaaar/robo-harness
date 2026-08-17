"""Pure lifecycle transition guards for Experiments and Episodes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from rh_core.errors import ErrorCode, LifecycleError, ValidationIssue
from rh_core.models import EpisodeState, ExperimentState, TerminationReason

_EXPERIMENT_TRANSITIONS: dict[ExperimentState, frozenset[ExperimentState]] = {
    ExperimentState.CREATED: frozenset({ExperimentState.STARTING}),
    ExperimentState.STARTING: frozenset({ExperimentState.RUNNING, ExperimentState.FAILED}),
    ExperimentState.RUNNING: frozenset({ExperimentState.FINALIZING, ExperimentState.FAILED}),
    ExperimentState.FINALIZING: frozenset(
        {ExperimentState.FINISHED, ExperimentState.FAILED}
    ),
    ExperimentState.FINISHED: frozenset(),
    ExperimentState.FAILED: frozenset(),
}

_EPISODE_TRANSITIONS: dict[EpisodeState, frozenset[EpisodeState]] = {
    EpisodeState.PREPARING: frozenset({EpisodeState.READY, EpisodeState.TERMINATING}),
    EpisodeState.READY: frozenset({EpisodeState.RUNNING, EpisodeState.TERMINATING}),
    EpisodeState.RUNNING: frozenset({EpisodeState.TERMINATING}),
    EpisodeState.TERMINATING: frozenset({EpisodeState.FINISHED}),
    EpisodeState.FINISHED: frozenset(),
}
_UINT64_MAX = 2**64 - 1


def _lifecycle_error(code: ErrorCode, path: str, message: str) -> LifecycleError:
    return LifecycleError((ValidationIssue(code=code, path=path, message=message),))


@dataclass(frozen=True, slots=True)
class ExperimentLifecycle:
    """Immutable snapshot of Experiment lifecycle state."""

    state: ExperimentState = ExperimentState.CREATED

    def __post_init__(self) -> None:
        if not isinstance(self.state, ExperimentState):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                "experiment.state",
                "state must be an ExperimentState",
            )

    def transition(self, target: ExperimentState) -> ExperimentLifecycle:
        """Return the next snapshot or reject an illegal transition."""

        if not isinstance(target, ExperimentState):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                "experiment.state",
                "target must be an ExperimentState",
            )
        if target not in _EXPERIMENT_TRANSITIONS[self.state]:
            raise _lifecycle_error(
                ErrorCode.INVALID_TRANSITION,
                "experiment.state",
                f"cannot transition from {self.state.name} to {target.name}",
            )
        return replace(self, state=target)


@dataclass(frozen=True, slots=True)
class EpisodeLifecycle:
    """Immutable Episode state with a monotonic transition sequence."""

    episode_id: str
    state: EpisodeState = EpisodeState.PREPARING
    termination_reason: TerminationReason = TerminationReason.NONE
    sequence: int = 0

    def __post_init__(self) -> None:
        path = f"episode[{self.episode_id}]"
        if not isinstance(self.episode_id, str):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                "episode.id",
                "episode_id must be a string",
            )
        if not self.episode_id.strip():
            raise _lifecycle_error(
                ErrorCode.INVALID_VALUE,
                "episode.id",
                "episode_id must not be empty",
            )
        if not isinstance(self.state, EpisodeState):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                f"{path}.state",
                "state must be an EpisodeState",
            )
        if not isinstance(self.termination_reason, TerminationReason):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                f"{path}.termination_reason",
                "termination_reason must be a TerminationReason",
            )
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                f"{path}.sequence",
                "sequence must be an integer",
            )
        if not 0 <= self.sequence <= _UINT64_MAX:
            raise _lifecycle_error(
                ErrorCode.INVALID_VALUE,
                f"{path}.sequence",
                "sequence must fit in an unsigned 64-bit integer",
            )

        reason_is_committed = self.termination_reason is not TerminationReason.NONE
        state_is_terminal = self.state in {EpisodeState.TERMINATING, EpisodeState.FINISHED}
        if state_is_terminal and not reason_is_committed:
            raise _lifecycle_error(
                ErrorCode.TERMINATION_REQUIRED,
                f"{path}.termination_reason",
                f"state {self.state.name} requires a non-NONE reason",
            )
        if not state_is_terminal and reason_is_committed:
            raise _lifecycle_error(
                ErrorCode.UNEXPECTED_TERMINATION_REASON,
                f"{path}.termination_reason",
                f"state {self.state.name} cannot carry a committed reason",
            )

    def transition(
        self,
        target: EpisodeState,
        *,
        termination_reason: TerminationReason | None = None,
    ) -> EpisodeLifecycle:
        """Return the next snapshot while enforcing one-time termination commit."""

        path = f"episode[{self.episode_id}].state"
        if not isinstance(target, EpisodeState):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                path,
                "target must be an EpisodeState",
            )
        if termination_reason is not None and not isinstance(
            termination_reason, TerminationReason
        ):
            raise _lifecycle_error(
                ErrorCode.TYPE_MISMATCH,
                f"episode[{self.episode_id}].termination_reason",
                "termination_reason must be a TerminationReason",
            )
        if target not in _EPISODE_TRANSITIONS[self.state]:
            raise _lifecycle_error(
                ErrorCode.INVALID_TRANSITION,
                path,
                f"cannot transition from {self.state.name} to {target.name}",
            )

        if self.termination_reason is not TerminationReason.NONE:
            if termination_reason is not None:
                raise _lifecycle_error(
                    ErrorCode.TERMINATION_ALREADY_COMMITTED,
                    f"episode[{self.episode_id}].termination_reason",
                    f"termination reason is already {self.termination_reason.name}",
                )
            next_reason = self.termination_reason
        elif target is EpisodeState.TERMINATING:
            if termination_reason in (None, TerminationReason.NONE):
                raise _lifecycle_error(
                    ErrorCode.TERMINATION_REQUIRED,
                    f"episode[{self.episode_id}].termination_reason",
                    "entering TERMINATING requires a non-NONE reason",
                )
            next_reason = termination_reason
        elif termination_reason is not None:
            raise _lifecycle_error(
                ErrorCode.UNEXPECTED_TERMINATION_REASON,
                f"episode[{self.episode_id}].termination_reason",
                "a reason can only be committed when entering TERMINATING",
            )
        else:
            next_reason = TerminationReason.NONE

        if self.sequence == _UINT64_MAX:
            raise _lifecycle_error(
                ErrorCode.INVALID_VALUE,
                f"episode[{self.episode_id}].sequence",
                "sequence cannot be incremented beyond uint64",
            )

        return replace(
            self,
            state=target,
            termination_reason=next_reason,
            sequence=self.sequence + 1,
        )
