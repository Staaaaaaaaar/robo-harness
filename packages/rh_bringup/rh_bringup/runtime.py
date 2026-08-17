"""Explicit composition root for the Experiment container."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from rclpy.node import Node

from rh_core import EpisodeSpec
from rh_eval_simple_navigation import SimpleNavigationObserver
from rh_experiment import (
    EpisodeEvaluatorFactory,
    EpisodeTaskPublisherFactory,
    TerminationSubmitter,
)
from rh_experiment.orchestrator import main as experiment_main
from rh_pointnav import PointNavTaskPublisher


@dataclass(frozen=True, slots=True)
class RuntimeAssembly:
    task_publisher_factory: EpisodeTaskPublisherFactory
    evaluator_factory: EpisodeEvaluatorFactory


def _pointnav_task(
    node: Node,
    experiment_id: str,
    episode: EpisodeSpec,
) -> PointNavTaskPublisher:
    return PointNavTaskPublisher(node, experiment_id, episode)


def _simple_navigation(
    node: Node,
    experiment_id: str,
    episode: EpisodeSpec,
    submit_termination: TerminationSubmitter,
) -> SimpleNavigationObserver:
    return SimpleNavigationObserver(
        node,
        experiment_id,
        episode,
        submit_termination,
    )


ASSEMBLIES = {
    "pointnav_simple": RuntimeAssembly(
        task_publisher_factory=_pointnav_task,
        evaluator_factory=_simple_navigation,
    ),
}


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=tuple(ASSEMBLIES),
        default="pointnav_simple",
        help="Explicit Task/Evaluator assembly for the Experiment container",
    )
    options, ros_args = parser.parse_known_args(args)
    assembly = ASSEMBLIES[options.profile]
    experiment_main(
        ros_args,
        task_publisher_factory=assembly.task_publisher_factory,
        evaluator_factory=assembly.evaluator_factory,
    )
