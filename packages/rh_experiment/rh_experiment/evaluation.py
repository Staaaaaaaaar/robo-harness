"""In-process boundary between orchestration and an Episode evaluator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from rclpy.node import Node

from rh_core import EpisodeSpec, TerminationReason
from rh_experiment.controller import ControlDecision
from rh_experiment.recorder import EpisodeMetrics, TrajectoryPoint


class TerminationSubmitter(Protocol):
    """Submit a candidate to the orchestrator's serialized commit path."""

    def __call__(
        self,
        reason: TerminationReason,
        *,
        detail: str,
    ) -> ControlDecision: ...


@dataclass(frozen=True, slots=True)
class EpisodeEvaluationResult:
    """Recorder-ready immutable snapshot produced during safe finalization."""

    metrics: EpisodeMetrics
    trajectory: tuple[TrajectoryPoint, ...]


class EpisodeEvaluator(Protocol):
    """Per-Episode evaluator owned and disposed by the orchestrator."""

    def finalize(
        self,
        reason: TerminationReason,
        simulation_time_s: float,
    ) -> EpisodeEvaluationResult: ...

    def close(self) -> None: ...


EpisodeEvaluatorFactory = Callable[
    [Node, str, EpisodeSpec, TerminationSubmitter],
    EpisodeEvaluator,
]
