"""ROS-independent Experiment and Episode control decisions."""

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


class ExperimentController:
    """Own one ordered multi-Episode lifecycle without ROS side effects."""

    def __init__(
        self,
        *,
        experiment_id: str,
        episode_ids: tuple[str, ...],
        execution_mode: ExecutionMode,
    ) -> None:
        if not experiment_id.strip():
            raise ValueError("experiment_id must not be empty")
        if not episode_ids:
            raise ValueError("episode_ids must not be empty")
        if any(not isinstance(value, str) or not value.strip() for value in episode_ids):
            raise ValueError("episode_ids must contain non-empty strings")
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError("episode_ids must be unique")
        if not isinstance(execution_mode, ExecutionMode):
            raise TypeError("execution_mode must be an ExecutionMode")
        self.experiment_id = experiment_id
        self.execution_mode = execution_mode
        self._episode_ids = episode_ids
        self._episode_index = 0
        self._completed_episodes: list[EpisodeLifecycle] = []
        self.experiment = ExperimentLifecycle().transition(ExperimentState.STARTING)
        self.episode = EpisodeLifecycle(episode_id=episode_ids[0])

    @property
    def episode_index(self) -> int:
        return self._episode_index

    @property
    def has_next_episode(self) -> bool:
        return self._episode_index + 1 < len(self._episode_ids)

    @property
    def completed_episodes(self) -> tuple[EpisodeLifecycle, ...]:
        return tuple(self._completed_episodes)

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

    def finish_termination(self, *, stop_experiment: bool = False) -> None:
        self.episode = self.episode.transition(EpisodeState.FINISHED)
        self._completed_episodes.append(self.episode)
        if stop_experiment:
            self.fail_experiment()
        elif self.experiment.state is ExperimentState.RUNNING and not self.has_next_episode:
            self.experiment = self.experiment.transition(ExperimentState.FINALIZING)
            self.experiment = self.experiment.transition(ExperimentState.FINISHED)
        elif self.experiment.state is ExperimentState.STARTING:
            self.experiment = self.experiment.transition(ExperimentState.FAILED)

    def advance_episode(self) -> EpisodeLifecycle:
        """Open the next Episode after the previous one reached FINISHED."""

        if self.episode.state is not EpisodeState.FINISHED:
            raise RuntimeError("the active Episode must be FINISHED before advancing")
        if not self.has_next_episode:
            raise RuntimeError("there is no next Episode")
        if self.experiment.state is not ExperimentState.RUNNING:
            raise RuntimeError("the Experiment is not running")
        self._episode_index += 1
        self.episode = EpisodeLifecycle(
            episode_id=self._episode_ids[self._episode_index]
        )
        return self.episode

    def fail_experiment(self) -> None:
        if self.experiment.state in {ExperimentState.STARTING, ExperimentState.RUNNING}:
            self.experiment = self.experiment.transition(ExperimentState.FAILED)

    def _identity_mismatch(
        self, experiment_id: str, episode_id: str
    ) -> str | None:
        if experiment_id != self.experiment_id or episode_id != self.episode.episode_id:
            return "request identity does not match the active Episode"
        return None


class SingleEpisodeController(ExperimentController):
    """Compatibility wrapper for callers that intentionally own one Episode."""

    def __init__(
        self,
        *,
        experiment_id: str,
        episode_id: str,
        execution_mode: ExecutionMode,
    ) -> None:
        super().__init__(
            experiment_id=experiment_id,
            episode_ids=(episode_id,),
            execution_mode=execution_mode,
        )
