"""Validated immutable PointNav semantics independent of ROS transport."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rh_core import EpisodeSpec, Point3D, PointNavTaskSpec, Pose3D

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


class PointNavValidationError(ValueError):
    """PointNav input cannot be made safe and reproducible."""


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PointNavValidationError(f"{name} must be a non-empty string")
    return value


def _finite(values: tuple[object, ...], name: str) -> None:
    if not all(
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
        for value in values
    ):
        raise PointNavValidationError(f"{name} must contain only finite values")


@dataclass(frozen=True, slots=True)
class PointNavDefinition:
    """Complete immutable PointNav snapshot for one Episode.

    The goal is a 3D position. It deliberately has no target orientation.
    """

    experiment_id: str
    episode_id: str
    goal: Point3D
    success_radius_m: float
    timeout_s: float
    seed: int

    def __post_init__(self) -> None:
        _identifier(self.experiment_id, "experiment_id")
        _identifier(self.episode_id, "episode_id")
        if not isinstance(self.goal, Point3D):
            raise PointNavValidationError("goal must be a Point3D")
        if self.goal.frame_id != "map":
            raise PointNavValidationError("PointNav goal frame must be 'map'")
        _finite((self.goal.x, self.goal.y, self.goal.z), "goal")
        _finite((self.success_radius_m, self.timeout_s), "PointNav parameters")
        if self.success_radius_m <= 0.0:
            raise PointNavValidationError("success_radius_m must be positive")
        if self.timeout_s <= 0.0:
            raise PointNavValidationError("timeout_s must be positive")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not _INT64_MIN <= self.seed <= _INT64_MAX
        ):
            raise PointNavValidationError("seed must fit in a signed 64-bit integer")

    @classmethod
    def from_episode(
        cls,
        experiment_id: str,
        episode: EpisodeSpec,
    ) -> PointNavDefinition:
        if not isinstance(episode, EpisodeSpec):
            raise PointNavValidationError("episode must be an EpisodeSpec")
        pose = episode.initial_pose
        if not isinstance(pose, Pose3D):
            raise PointNavValidationError("initial pose must be a Pose3D")
        if not isinstance(episode.task, PointNavTaskSpec):
            raise PointNavValidationError("task must be a PointNavTaskSpec")
        if pose.frame_id != "map":
            raise PointNavValidationError("initial pose frame must be 'map'")
        _finite(
            (pose.x, pose.y, pose.z, pose.roll, pose.pitch, pose.yaw),
            "initial pose",
        )
        if pose.frame_id != episode.task.goal.frame_id:
            raise PointNavValidationError("initial pose and goal frames must match")
        return cls(
            experiment_id=experiment_id,
            episode_id=episode.episode_id,
            goal=episode.task.goal,
            success_radius_m=episode.task.success_radius_m,
            timeout_s=episode.task.timeout_s,
            seed=episode.seed,
        )

    def matches_episode(self, experiment_id: str, episode_id: str) -> bool:
        return (
            experiment_id == self.experiment_id
            and episode_id == self.episode_id
        )

    def distance_to_goal(self, position: Point3D) -> float:
        if not isinstance(position, Point3D):
            raise PointNavValidationError("position must be a Point3D")
        if position.frame_id != self.goal.frame_id:
            raise PointNavValidationError("position and goal frames must match")
        _finite((position.x, position.y, position.z), "position")
        return math.dist(
            (position.x, position.y, position.z),
            (self.goal.x, self.goal.y, self.goal.z),
        )

    def goal_reached(self, position: Point3D) -> bool:
        return self.distance_to_goal(position) <= self.success_radius_m

    def timed_out(self, elapsed_time_s: float) -> bool:
        if (
            isinstance(elapsed_time_s, bool)
            or not isinstance(elapsed_time_s, int | float)
            or not math.isfinite(elapsed_time_s)
            or elapsed_time_s < 0.0
        ):
            raise PointNavValidationError(
                "elapsed_time_s must be finite and non-negative"
            )
        return elapsed_time_s >= self.timeout_s
