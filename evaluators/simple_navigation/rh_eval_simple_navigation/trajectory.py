"""ROS-independent simulation-time trajectory sampling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rh_core import Point3D


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    simulation_time_s: float
    position: Point3D


class TrajectorySampler:
    """Accumulate ordered 3D map-frame samples for one running Episode."""

    def __init__(self, *, frame_id: str = "map") -> None:
        if not frame_id.strip():
            raise ValueError("frame_id must not be empty")
        self._frame_id = frame_id
        self.reset()

    @property
    def path_length_m(self) -> float:
        return self._path_length_m

    @property
    def samples(self) -> tuple[TrajectorySample, ...]:
        return tuple(self._samples)

    @property
    def final_position(self) -> Point3D | None:
        return self._samples[-1].position if self._samples else None

    @property
    def final_time_s(self) -> float | None:
        return self._samples[-1].simulation_time_s if self._samples else None

    def reset(self) -> None:
        """Start a new segment so reset motion is never counted as travel."""

        self._samples: list[TrajectorySample] = []
        self._path_length_m = 0.0

    def observe(self, simulation_time_s: float, position: Point3D) -> bool:
        """Accept one strictly newer sample; return false for stale duplicates."""

        if (
            isinstance(simulation_time_s, bool)
            or not isinstance(simulation_time_s, int | float)
            or not math.isfinite(simulation_time_s)
            or simulation_time_s < 0.0
        ):
            raise ValueError("simulation_time_s must be finite and non-negative")
        if not isinstance(position, Point3D):
            raise TypeError("position must be a Point3D")
        if position.frame_id != self._frame_id:
            raise ValueError(f"position frame must be {self._frame_id!r}")
        if not all(math.isfinite(value) for value in (position.x, position.y, position.z)):
            raise ValueError("position must contain only finite values")
        timestamp = float(simulation_time_s)
        if self._samples and timestamp <= self._samples[-1].simulation_time_s:
            return False
        if self._samples:
            previous = self._samples[-1].position
            self._path_length_m += math.dist(
                (previous.x, previous.y, previous.z),
                (position.x, position.y, position.z),
            )
        self._samples.append(TrajectorySample(timestamp, position))
        return True
