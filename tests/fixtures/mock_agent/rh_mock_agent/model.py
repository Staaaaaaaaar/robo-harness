"""ROS-independent deterministic state model for the Mock Agent fixture."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class VelocityCommand:
    """Planar body command emitted by one scripted segment."""

    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0


ZERO_COMMAND = VelocityCommand()


@dataclass(frozen=True, slots=True)
class ScriptSegment:
    """One immutable command and its simulation-time duration."""

    duration_ns: int
    command: VelocityCommand

    def __post_init__(self) -> None:
        values = (
            self.command.linear_x,
            self.command.linear_y,
            self.command.angular_z,
        )
        if (
            isinstance(self.duration_ns, bool)
            or not isinstance(self.duration_ns, int)
            or self.duration_ns <= 0
        ):
            raise ValueError("segment duration_ns must be a positive integer")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("segment command must contain only finite values")


@dataclass(frozen=True, slots=True)
class MockAgentSnapshot:
    """Complete observable state needed by contract tests."""

    experiment_id: str | None = None
    episode_id: str | None = None
    task_fingerprint: tuple[object, ...] | None = None
    episode_running: bool = False
    script_elapsed_ns: int = 0
    command: VelocityCommand = ZERO_COMMAND


class MockAgentModel:
    """Gate a fixed command script by reset, task, state, and simulation time.

    This model deliberately contains no navigation or goal-following behavior.
    It only gives integration tests a deterministic Agent-side command source.
    """

    def __init__(self, script: tuple[ScriptSegment, ...]) -> None:
        if not script:
            raise ValueError("script must contain at least one segment")
        self._script = script
        self._snapshot = MockAgentSnapshot()
        self._last_clock_ns: int | None = None

    @property
    def snapshot(self) -> MockAgentSnapshot:
        return self._snapshot

    def reset(self, experiment_id: str, episode_id: str) -> None:
        """Activate an Episode and clear every task/script/command state."""

        if not experiment_id.strip() or not episode_id.strip():
            raise ValueError("experiment_id and episode_id must not be empty")
        self._snapshot = MockAgentSnapshot(
            experiment_id=experiment_id,
            episode_id=episode_id,
        )
        self._last_clock_ns = None

    def accept_task(
        self,
        experiment_id: str,
        episode_id: str,
        fingerprint: tuple[object, ...],
    ) -> bool:
        """Accept the first matching immutable task; allow identical replay."""

        if (
            experiment_id != self._snapshot.experiment_id
            or episode_id != self._snapshot.episode_id
        ):
            return False
        existing = self._snapshot.task_fingerprint
        if existing is not None and existing != fingerprint:
            return False
        self._snapshot = replace(self._snapshot, task_fingerprint=fingerprint)
        self._refresh_command()
        return True

    def set_episode_running(self, running: bool) -> None:
        self._snapshot = replace(self._snapshot, episode_running=running)
        if not running:
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            self._last_clock_ns = None
        else:
            self._refresh_command()

    def advance_clock(self, simulation_time_ns: int) -> bool:
        """Advance the script by simulation time; reject backward time jumps."""

        if (
            isinstance(simulation_time_ns, bool)
            or not isinstance(simulation_time_ns, int)
            or simulation_time_ns < 0
        ):
            raise ValueError("simulation_time_ns must be a non-negative integer")
        if not self._can_drive:
            self._last_clock_ns = simulation_time_ns
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            return False
        if self._last_clock_ns is None:
            self._last_clock_ns = simulation_time_ns
            self._refresh_command()
            return True
        if simulation_time_ns < self._last_clock_ns:
            self._last_clock_ns = simulation_time_ns
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            return False

        elapsed = self._snapshot.script_elapsed_ns + (
            simulation_time_ns - self._last_clock_ns
        )
        self._last_clock_ns = simulation_time_ns
        self._snapshot = replace(self._snapshot, script_elapsed_ns=elapsed)
        self._refresh_command()
        return True

    @property
    def _can_drive(self) -> bool:
        return self._snapshot.episode_running and self._snapshot.task_fingerprint is not None

    def _refresh_command(self) -> None:
        if not self._can_drive:
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            return
        remaining = self._snapshot.script_elapsed_ns
        for segment in self._script:
            if remaining < segment.duration_ns:
                self._snapshot = replace(self._snapshot, command=segment.command)
                return
            remaining -= segment.duration_ns
        self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
