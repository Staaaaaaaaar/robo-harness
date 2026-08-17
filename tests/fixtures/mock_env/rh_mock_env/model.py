"""Deterministic fixed-step model used only by the Mock Environment fixture."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from rh_core import Pose3D


@dataclass(frozen=True, slots=True)
class VelocityCommand:
    """Planar body-frame command understood by the MVP mock model."""

    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0


ZERO_COMMAND = VelocityCommand()


@dataclass(frozen=True, slots=True)
class MockEnvironmentSnapshot:
    """Observable deterministic state of the fixture."""

    pose: Pose3D
    command: VelocityCommand
    simulation_time_ns: int
    episode_running: bool


class MockEnvironmentModel:
    """Integrate a planar command with fixed simulation-time steps.

    This is a protocol fixture, not a physics simulator. Position is integrated
    exactly once per requested step; roll, pitch, and height remain as reset.
    """

    def __init__(self, *, command_timeout_s: float) -> None:
        if not math.isfinite(command_timeout_s) or command_timeout_s <= 0.0:
            raise ValueError("command_timeout_s must be finite and positive")
        self._command_timeout_ns = round(command_timeout_s * 1_000_000_000)
        self._snapshot = MockEnvironmentSnapshot(
            pose=Pose3D("map", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            command=ZERO_COMMAND,
            simulation_time_ns=0,
            episode_running=False,
        )
        self._last_command_time_ns: int | None = None

    @property
    def snapshot(self) -> MockEnvironmentSnapshot:
        return self._snapshot

    def reset(self, pose: Pose3D) -> None:
        """Apply the complete initial pose without rewinding global sim time."""

        self._snapshot = replace(
            self._snapshot,
            pose=pose,
            command=ZERO_COMMAND,
            episode_running=False,
        )
        self._last_command_time_ns = None

    def set_episode_running(self, running: bool) -> None:
        self._snapshot = replace(self._snapshot, episode_running=running)
        if not running:
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            self._last_command_time_ns = None

    def receive_command(self, command: VelocityCommand) -> bool:
        """Accept commands only while RUNNING; otherwise preserve the zero gate."""

        values = (command.linear_x, command.linear_y, command.angular_z)
        if not all(math.isfinite(value) for value in values):
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            self._last_command_time_ns = None
            return False
        if not self._snapshot.episode_running:
            self._snapshot = replace(self._snapshot, command=ZERO_COMMAND)
            return False
        self._snapshot = replace(self._snapshot, command=command)
        self._last_command_time_ns = self._snapshot.simulation_time_ns
        return True

    def step(self, step_ns: int) -> None:
        """Advance by one exact simulation step and enforce the command watchdog."""

        if isinstance(step_ns, bool) or not isinstance(step_ns, int) or step_ns <= 0:
            raise ValueError("step_ns must be a positive integer")
        next_time = self._snapshot.simulation_time_ns + step_ns
        command = self._snapshot.command
        if (
            not self._snapshot.episode_running
            or self._last_command_time_ns is None
            or next_time - self._last_command_time_ns > self._command_timeout_ns
        ):
            command = ZERO_COMMAND

        pose = self._snapshot.pose
        dt = step_ns / 1_000_000_000.0
        cos_yaw = math.cos(pose.yaw)
        sin_yaw = math.sin(pose.yaw)
        next_pose = replace(
            pose,
            x=pose.x + (command.linear_x * cos_yaw - command.linear_y * sin_yaw) * dt,
            y=pose.y + (command.linear_x * sin_yaw + command.linear_y * cos_yaw) * dt,
            yaw=pose.yaw + command.angular_z * dt,
        )
        self._snapshot = replace(
            self._snapshot,
            pose=next_pose,
            command=command,
            simulation_time_ns=next_time,
        )
