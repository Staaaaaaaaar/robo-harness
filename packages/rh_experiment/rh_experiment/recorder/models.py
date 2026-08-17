"""Typed inputs accepted by the durable result recorder."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from rh_core import TerminationReason


def _finite_non_negative(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0.0
    ):
        raise ValueError(f"{name} must be finite and non-negative")
    return float(value)


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Reproducibility metadata supplied by deployment or CI."""

    git_sha: str | None = None
    image_digests: dict[str, str] = field(default_factory=dict)
    ros_distro: str | None = None
    isaac_version: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("git_sha", self.git_sha),
            ("ros_distro", self.ros_distro),
            ("isaac_version", self.isaac_version),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be None or a non-empty string")
        if not isinstance(self.image_digests, dict) or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(digest, str)
            or not digest.strip()
            for name, digest in self.image_digests.items()
        ):
            raise ValueError("image_digests must map non-empty strings to strings")


@dataclass(frozen=True, slots=True)
class EpisodeMetrics:
    """Stable, evaluator-independent metric snapshot for one Episode."""

    success: bool
    elapsed_time_s: float
    path_length_m: float
    final_distance_to_goal_m: float | None
    timeout: bool
    termination_reason: TerminationReason
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool) or not isinstance(self.timeout, bool):
            raise TypeError("success and timeout must be bool values")
        object.__setattr__(
            self,
            "elapsed_time_s",
            _finite_non_negative(self.elapsed_time_s, "elapsed_time_s"),
        )
        object.__setattr__(
            self,
            "path_length_m",
            _finite_non_negative(self.path_length_m, "path_length_m"),
        )
        if self.final_distance_to_goal_m is not None:
            object.__setattr__(
                self,
                "final_distance_to_goal_m",
                _finite_non_negative(
                    self.final_distance_to_goal_m,
                    "final_distance_to_goal_m",
                ),
            )
        if not isinstance(self.termination_reason, TerminationReason):
            raise TypeError("termination_reason must be a TerminationReason")
        if self.termination_reason is TerminationReason.NONE:
            raise ValueError("completed metrics require a termination reason")
        if self.success != (self.termination_reason is TerminationReason.SUCCESS):
            raise ValueError("success must agree with termination_reason")
        if self.timeout != (self.termination_reason is TerminationReason.TIMEOUT):
            raise ValueError("timeout must agree with termination_reason")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 0
        ):
            raise ValueError("sample_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    """One ordered ground-truth position sample."""

    simulation_time_s: float
    frame_id: str
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "simulation_time_s",
            _finite_non_negative(self.simulation_time_s, "simulation_time_s"),
        )
        if not isinstance(self.frame_id, str) or not self.frame_id.strip():
            raise ValueError("frame_id must be a non-empty string")
        for name in ("x", "y", "z"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, float(value))


@dataclass(frozen=True, slots=True)
class ResultEvent:
    """Low-rate lifecycle or evaluation event stored as one JSONL record."""

    sequence: int
    event: str
    simulation_time_s: float | None = None
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a non-negative integer")
        if not isinstance(self.event, str) or not self.event.strip():
            raise ValueError("event must be a non-empty string")
        if self.simulation_time_s is not None:
            object.__setattr__(
                self,
                "simulation_time_s",
                _finite_non_negative(self.simulation_time_s, "simulation_time_s"),
            )
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dictionary")
        try:
            json.dumps(self.payload, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("payload must contain finite JSON values") from error
