"""ROS-independent single-Episode control decisions."""

from __future__ import annotations

from dataclasses import dataclass

from rh_core import (
    EpisodeLifecycle,
    EpisodeState,
    ExecutionMode,
    ExperimentLifecycle,
    ExperimentState,
    TerminationReason,
)


@dataclass(frozen=True, slots=True)
class ControlDecision:
    accepted: bool
    detail: str


class SingleEpisodeController:
    """Own legal Experiment and Episode transitions without ROS side effects."""

    def __init__(
        self,
        *,
        experiment_id: str,
        episode_id: str,
        execution_mode: ExecutionMode,
    ) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id must not be empty")
        if not isinstance(execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        self.experiment_id = experiment_id
        self.execution_mode = execution_mode
        self.experiment = ExperimentLifecycle().transition(ExperimentState.STARTING)
        self.episode = EpisodeLifecycle(episode_id=episode_id)

    def mark_components_ready(self) -> None:
        """Finish Experiment startup before reset/task preparation begins."""

        self.experiment = self.experiment.transition(ExperimentState.RUNNING)

    def mark_prepared(self) -> None:
        self.episode = self.episode.transition(EpisodeState.READY)

    def request_start(self, experiment_id: str, episode_id: str) -> ControlDecision:
        mismatch = self._identity_mismatch(experiment_id, episode_id)
        if mismatch is not None:
            return ControlDecision(False, mismatch)
        if self.episode.state is not EpisodeState.READY:
            return ControlDecision(
                False,
                f"episode is {self.episode.state.name}, expected READY",
            )
        self.episode = self.episode.transition(EpisodeState.RUNNING)
        return ControlDecision(True, "episode started")

    def request_termination(
        self,
        reason: TerminationReason,
        *,
        detail: str,
    ) -> ControlDecision:
        if reason is TerminationReason.NONE:
            return ControlDecision(False, "termination reason must not be NONE")
        if self.episode.state not in {
            EpisodeState.PREPARING,
            EpisodeState.READY,
            EpisodeState.RUNNING,
        }:
            return ControlDecision(
                False,
                f"termination is already committed as {self.episode.termination_reason.name}",
            )
        self.episode = self.episode.transition(
            EpisodeState.TERMINATING,
            termination_reason=reason,
        )
        return ControlDecision(True, detail)

    def request_abort(
        self,
        experiment_id: str,
        episode_id: str,
        reason: str,
    ) -> ControlDecision:
        mismatch = self._identity_mismatch(experiment_id, episode_id)
        if mismatch is not None:
            return ControlDecision(False, mismatch)
        if not reason.strip():
            return ControlDecision(False, "abort reason must not be empty")
        return self.request_termination(
            TerminationReason.ABORTED,
            detail=f"abort accepted: {reason.strip()}",
        )

    def finish_termination(self) -> None:
        self.episode = self.episode.transition(EpisodeState.FINISHED)
        if self.experiment.state is ExperimentState.RUNNING:
            self.experiment = self.experiment.transition(ExperimentState.FINALIZING)
            self.experiment = self.experiment.transition(ExperimentState.FINISHED)
        elif self.experiment.state is ExperimentState.STARTING:
            self.experiment = self.experiment.transition(ExperimentState.FAILED)

    def fail_experiment(self) -> None:
        if self.experiment.state in {ExperimentState.STARTING, ExperimentState.RUNNING}:
            self.experiment = self.experiment.transition(ExperimentState.FAILED)

    def _identity_mismatch(
        self, experiment_id: str, episode_id: str
    ) -> str | None:
        if experiment_id != self.experiment_id or episode_id != self.episode.episode_id:
            return "request identity does not match the active Episode"
        return None
