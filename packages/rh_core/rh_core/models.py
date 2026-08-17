"""Typed domain models shared by RoboHarness core behavior."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class ExecutionMode(str, Enum):
    """How a READY Episode is triggered."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"


class ExperimentState(IntEnum):
    """Authoritative lifecycle of one Experiment run."""

    CREATED = 0
    STARTING = 1
    RUNNING = 2
    FINALIZING = 3
    FINISHED = 4
    FAILED = 5


class EpisodeState(IntEnum):
    """Authoritative lifecycle of one Episode."""

    PREPARING = 0
    READY = 1
    RUNNING = 2
    TERMINATING = 3
    FINISHED = 4


class TerminationReason(IntEnum):
    """Why an Episode stopped; orthogonal to its lifecycle state."""

    NONE = 0
    SUCCESS = 1
    TIMEOUT = 2
    ABORTED = 3
    FAILURE = 4
    ENV_ERROR = 5
    AGENT_ERROR = 6
    INVALID_TASK = 7


@dataclass(frozen=True, slots=True)
class Point3D:
    """Three-dimensional point expressed in a named coordinate frame."""

    frame_id: str
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class Pose3D:
    """Robot pose using metres and fixed-axis X-Y-Z roll/pitch/yaw radians."""

    frame_id: str
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float


@dataclass(frozen=True, slots=True)
class PointNavTaskSpec:
    """Immutable static input for a PointNav Episode."""

    goal: Point3D
    success_radius_m: float
    timeout_s: float


@dataclass(frozen=True, slots=True)
class EpisodeSpec:
    """Validated and immutable description of one Episode."""

    episode_id: str
    scenario: str
    initial_pose: Pose3D
    task: PointNavTaskSpec
    seed: int


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """Ordered collection of Episode specifications."""

    name: str
    execution_mode: ExecutionMode
    episodes: tuple[EpisodeSpec, ...]


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Versioned, validated root configuration document."""

    schema_version: int
    experiment: ExperimentSpec
