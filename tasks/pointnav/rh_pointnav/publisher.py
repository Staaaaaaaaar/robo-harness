"""Transient-local publication of one immutable PointNav task snapshot."""

from __future__ import annotations

from copy import deepcopy

from rclpy.node import Node
from rh_interfaces.msg import PointNavTask

from rh_core import EpisodeSpec
from rh_pointnav.definition import PointNavDefinition
from rh_ros import latched_control_qos, point_to_message


class PointNavTaskPublisher:
    """Validate at construction and publish an unchanged task snapshot."""

    def __init__(
        self,
        node: Node,
        experiment_id: str,
        episode: EpisodeSpec,
        *,
        topic: str = "/roboharness/task/pointnav",
    ) -> None:
        self._node = node
        self.definition = PointNavDefinition.from_episode(experiment_id, episode)
        self._publisher = node.create_publisher(
            PointNavTask,
            topic,
            latched_control_qos(),
        )
        self._message = self._build_message()
        self._publish_count = 0

    @property
    def message(self) -> PointNavTask:
        return deepcopy(self._message)

    @property
    def publish_count(self) -> int:
        return self._publish_count

    def publish(self) -> None:
        self._publisher.publish(self._message)
        self._publish_count += 1

    def close(self) -> None:
        """Release the transient-local publisher before the next Episode."""

        if self._publisher is not None:
            self._node.destroy_publisher(self._publisher)
            self._publisher = None

    def _build_message(self) -> PointNavTask:
        definition = self.definition
        message = PointNavTask()
        message.experiment_id = definition.experiment_id
        message.episode_id = definition.episode_id
        message.goal = point_to_message(
            definition.goal,
            stamp=self._node.get_clock().now().to_msg(),
        )
        message.success_radius_m = definition.success_radius_m
        message.timeout_s = definition.timeout_s
        message.seed = definition.seed
        return message
