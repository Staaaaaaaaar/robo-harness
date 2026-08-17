"""In-process boundary between orchestration and an Episode evaluator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rclpy.node import Node

from rh_core import EpisodeSpec, TerminationReason
from rh_experiment.controller import ControlDecision


class TerminationSubmitter(Protocol):
    """Submit a candidate to the orchestrator's serialized commit path."""

    def __call__(
        self,
        reason: TerminationReason,
        *,
        detail: str,
    ) -> ControlDecision: ...


class EpisodeEvaluator(Protocol):
    """Marker protocol for an evaluator owned by an Experiment process."""


EpisodeEvaluatorFactory = Callable[
    [Node, str, EpisodeSpec, TerminationSubmitter],
    EpisodeEvaluator,
]
