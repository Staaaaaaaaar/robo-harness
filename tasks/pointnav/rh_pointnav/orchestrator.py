"""PointNav composition entrypoint for the generic Experiment orchestrator."""

from __future__ import annotations

from rclpy.node import Node

from rh_core import EpisodeSpec
from rh_experiment.orchestrator import main as experiment_main
from rh_pointnav.publisher import PointNavTaskPublisher


def _pointnav_publisher_factory(
    node: Node,
    experiment_id: str,
    episode: EpisodeSpec,
) -> PointNavTaskPublisher:
    return PointNavTaskPublisher(node, experiment_id, episode)


def main(args: list[str] | None = None) -> None:
    experiment_main(
        args,
        task_publisher_factory=_pointnav_publisher_factory,
    )
