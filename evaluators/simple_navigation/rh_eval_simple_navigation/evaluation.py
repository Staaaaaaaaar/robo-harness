"""Pure PointNav evaluation and termination-candidate logic."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rh_core import Point3D, TerminationReason
from rh_eval_simple_navigation.trajectory import TrajectorySampler
from rh_pointnav import PointNavDefinition


@dataclass(frozen=True, slots=True)
class TerminationCandidate:
    reason: TerminationReason
    simulation_time_s: float
    detail: str


@dataclass(frozen=True, slots=True)
class NavigationMetrics:
    success: bool
    elapsed_time_s: float
    path_length_m: float
    final_distance_to_goal_m: float | None
    timeout: bool
    termination_reason: TerminationReason
    sample_count: int


class SimpleNavigationEvaluation:
    """Evaluate exactly one validated PointNav Episode."""

    def __init__(self, definition: PointNavDefinition) -> None:
        if not isinstance(definition, PointNavDefinition):
            raise TypeError("definition must be a PointNavDefinition")
        self.definition = definition
        self.trajectory = TrajectorySampler(frame_id=definition.goal.frame_id)
        self.prepare()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def candidate(self) -> TerminationCandidate | None:
        return self._candidate

    @property
    def metrics(self) -> NavigationMetrics:
        final_position = self.trajectory.final_position
        final_distance = (
            self.definition.distance_to_goal(final_position)
            if final_position is not None
            else None
        )
        return NavigationMetrics(
            success=self._termination_reason is TerminationReason.SUCCESS,
            elapsed_time_s=self._elapsed_time_s,
            path_length_m=self.trajectory.path_length_m,
            final_distance_to_goal_m=final_distance,
            timeout=self._termination_reason is TerminationReason.TIMEOUT,
            termination_reason=self._termination_reason,
            sample_count=len(self.trajectory.samples),
        )

    def prepare(self) -> None:
        self.trajectory.reset()
        self._start_time_s: float | None = None
        self._last_clock_time_s: float | None = None
        self._elapsed_time_s = 0.0
        self._candidate: TerminationCandidate | None = None
        self._termination_reason = TerminationReason.NONE
        self._agent_success_time_s: float | None = None
        self._running = False

    def start(self, simulation_time_s: float) -> None:
        start_time = self._valid_time(simulation_time_s)
        if self._running:
            return
        self._start_time_s = start_time
        self._last_clock_time_s = start_time
        self._elapsed_time_s = 0.0
        self._running = True

    def observe_position(
        self,
        simulation_time_s: float,
        position: Point3D,
    ) -> TerminationCandidate | None:
        timestamp = self._valid_time(simulation_time_s)
        if not self._running or self._start_time_s is None:
            return None
        if timestamp < self._start_time_s:
            return None
        if not self.trajectory.observe(timestamp, position):
            return None
        self._advance_elapsed(timestamp)
        if (
            self._agent_success_time_s is not None
            and timestamp >= self._agent_success_time_s
        ):
            reason = (
                TerminationReason.SUCCESS
                if self.definition.goal_reached(position)
                else TerminationReason.FAILURE
            )
            return self._commit_candidate(reason, timestamp)
        if self.definition.timed_out(self._elapsed_time_s):
            return self._commit_candidate(TerminationReason.TIMEOUT, timestamp)
        return None

    def report_agent_succeeded(
        self,
        simulation_time_s: float,
    ) -> TerminationCandidate | None:
        """Record Agent completion and confirm it against final ground truth."""

        timestamp = self._valid_time(simulation_time_s)
        if not self._running or self._start_time_s is None:
            return None
        if timestamp < self._start_time_s:
            return None
        if self._agent_success_time_s is None:
            self._agent_success_time_s = timestamp
        self._advance_elapsed(timestamp)
        final_position = self.trajectory.final_position
        final_time = self.trajectory.final_time_s
        if (
            final_position is None
            or final_time is None
            or final_time < self._agent_success_time_s
        ):
            return None
        reason = (
            TerminationReason.SUCCESS
            if self.definition.goal_reached(final_position)
            else TerminationReason.FAILURE
        )
        return self._commit_candidate(reason, timestamp)

    def report_agent_failed(
        self,
        simulation_time_s: float,
    ) -> TerminationCandidate | None:
        timestamp = self._valid_time(simulation_time_s)
        if not self._running or self._start_time_s is None:
            return None
        if timestamp < self._start_time_s:
            return None
        self._advance_elapsed(timestamp)
        return self._commit_candidate(TerminationReason.FAILURE, timestamp)

    def advance_clock(self, simulation_time_s: float) -> TerminationCandidate | None:
        timestamp = self._valid_time(simulation_time_s)
        if not self._running or self._start_time_s is None:
            return None
        if timestamp <= self._last_clock_time_s:
            return None
        self._last_clock_time_s = timestamp
        self._advance_elapsed(timestamp)
        if self.definition.timed_out(self._elapsed_time_s):
            return self._commit_candidate(TerminationReason.TIMEOUT, timestamp)
        return None

    def finish(
        self,
        reason: TerminationReason,
        simulation_time_s: float,
    ) -> None:
        if not isinstance(reason, TerminationReason):
            raise TypeError("reason must be a TerminationReason")
        timestamp = self._valid_time(simulation_time_s)
        if self._start_time_s is not None:
            self._advance_elapsed(timestamp)
        self._termination_reason = reason
        self._running = False

    def _commit_candidate(
        self,
        reason: TerminationReason,
        simulation_time_s: float,
    ) -> TerminationCandidate | None:
        if self._candidate is not None:
            return None
        self._termination_reason = reason
        self._running = False
        labels = {
            TerminationReason.SUCCESS: "agent completion confirmed at goal",
            TerminationReason.TIMEOUT: "timeout",
            TerminationReason.FAILURE: "agent execution ended without confirmed success",
        }
        label = labels[reason]
        self._candidate = TerminationCandidate(
            reason=reason,
            simulation_time_s=simulation_time_s,
            detail=f"PointNav {label} at {self._elapsed_time_s:.6f} simulation seconds",
        )
        return self._candidate

    def _advance_elapsed(self, simulation_time_s: float) -> None:
        assert self._start_time_s is not None
        self._elapsed_time_s = max(
            self._elapsed_time_s,
            simulation_time_s - self._start_time_s,
        )

    @staticmethod
    def _valid_time(value: float) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value < 0.0
        ):
            raise ValueError("simulation time must be finite and non-negative")
        return float(value)
