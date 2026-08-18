"""ROS observer that feeds the pure PointNav evaluation."""

from __future__ import annotations

import threading
from copy import deepcopy

from builtin_interfaces.msg import Time
from geometry_msgs.msg import PointStamped
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time as RclpyTime
from rh_interfaces.msg import AgentTaskState, PointNavTask
from rh_interfaces.msg import EpisodeState as EpisodeStateMessage
from rosgraph_msgs.msg import Clock
from tf2_geometry_msgs import do_transform_point
from tf2_ros import Buffer, TransformException, TransformListener

from rh_core import EpisodeSpec, EpisodeState, Point3D, TerminationReason
from rh_eval_simple_navigation.evaluation import (
    NavigationMetrics,
    SimpleNavigationEvaluation,
    TerminationCandidate,
)
from rh_eval_simple_navigation.trajectory import TrajectorySample
from rh_experiment import (
    EpisodeEvaluationResult,
    EpisodeMetrics,
    TerminationSubmitter,
    TrajectoryPoint,
)
from rh_pointnav import PointNavDefinition, PointNavValidationError
from rh_ros import (
    ConversionError,
    episode_state_values_from_message,
    latched_control_qos,
    point_from_message,
    sensor_qos,
)


def _seconds(stamp: Time) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0


class SimpleNavigationObserver:
    """Observe PointNav state and telemetry without publishing robot commands."""

    def __init__(
        self,
        node: Node,
        experiment_id: str,
        episode: EpisodeSpec,
        submit_termination: TerminationSubmitter,
    ) -> None:
        self._node = node
        self._expected = PointNavDefinition.from_episode(experiment_id, episode)
        self._evaluation = SimpleNavigationEvaluation(self._expected)
        self._submit_termination = submit_termination
        self._lock = threading.Lock()
        self._task_verified = False
        self._last_state_sequence: int | None = None
        self._last_agent_state_sequence: int | None = None
        self._pending_agent_terminal: tuple[int, float] | None = None
        self._candidate_submitted = False
        self._tf_buffer = Buffer(node=node)
        self._tf_listener = TransformListener(
            self._tf_buffer,
            node,
            spin_thread=False,
        )

        self._task_subscription = node.create_subscription(
            PointNavTask,
            "/roboharness/task/pointnav",
            self._on_task,
            latched_control_qos(),
        )
        self._state_subscription = node.create_subscription(
            EpisodeStateMessage,
            "/roboharness/episode/state",
            self._on_state,
            latched_control_qos(),
        )
        self._agent_state_subscription = node.create_subscription(
            AgentTaskState,
            "/roboharness/agent/task_state",
            self._on_agent_task_state,
            latched_control_qos(),
        )
        self._odom_subscription = node.create_subscription(
            Odometry,
            "/robot/odom",
            self._on_odometry,
            sensor_qos(),
        )
        self._clock_subscription = node.create_subscription(
            Clock,
            "/clock",
            self._on_clock,
            1,
        )

    @property
    def task_verified(self) -> bool:
        with self._lock:
            return self._task_verified

    @property
    def metrics(self) -> NavigationMetrics:
        with self._lock:
            return deepcopy(self._evaluation.metrics)

    @property
    def samples(self) -> tuple[TrajectorySample, ...]:
        with self._lock:
            return tuple(self._evaluation.trajectory.samples)

    def transform_ready(self, source_frame: str) -> bool:
        """Report whether telemetry can currently be transformed into map."""

        return self._tf_buffer.can_transform(
            self._expected.goal.frame_id,
            source_frame,
            RclpyTime(),
        )

    def finalize(
        self,
        reason: TerminationReason,
        simulation_time_s: float,
    ) -> EpisodeEvaluationResult:
        """Freeze one Episode and return its durable recorder representation."""

        with self._lock:
            self._evaluation.finish(reason, simulation_time_s)
            metrics = self._evaluation.metrics
            samples = tuple(self._evaluation.trajectory.samples)
        return EpisodeEvaluationResult(
            metrics=EpisodeMetrics(
                success=metrics.success,
                elapsed_time_s=metrics.elapsed_time_s,
                path_length_m=metrics.path_length_m,
                final_distance_to_goal_m=metrics.final_distance_to_goal_m,
                timeout=metrics.timeout,
                termination_reason=metrics.termination_reason,
                sample_count=metrics.sample_count,
            ),
            trajectory=tuple(
                TrajectoryPoint(
                    simulation_time_s=sample.simulation_time_s,
                    frame_id=sample.position.frame_id,
                    x=sample.position.x,
                    y=sample.position.y,
                    z=sample.position.z,
                )
                for sample in samples
            ),
        )

    def close(self) -> None:
        """Destroy Episode-scoped ROS entities so old callbacks cannot leak."""

        for subscription in (
            self._task_subscription,
            self._state_subscription,
            self._agent_state_subscription,
            self._odom_subscription,
            self._clock_subscription,
        ):
            self._node.destroy_subscription(subscription)
        unregister = getattr(self._tf_listener, "unregister", None)
        if callable(unregister):
            unregister()

    def _on_task(self, message: PointNavTask) -> None:
        try:
            received = PointNavDefinition(
                experiment_id=message.experiment_id,
                episode_id=message.episode_id,
                goal=point_from_message(message.goal),
                success_radius_m=message.success_radius_m,
                timeout_s=message.timeout_s,
                seed=message.seed,
            )
        except (ConversionError, PointNavValidationError) as error:
            self._node.get_logger().warning(f"ignoring invalid PointNav task: {error}")
            return
        if received != self._expected:
            self._node.get_logger().warning(
                "ignoring PointNav task that does not match the active Episode"
            )
            return
        with self._lock:
            self._task_verified = True

    def _on_state(self, message: EpisodeStateMessage) -> None:
        if not self._matches(message.experiment_id, message.episode_id):
            return
        try:
            state, reason = episode_state_values_from_message(message)
        except ConversionError as error:
            self._node.get_logger().warning(f"ignoring invalid Episode state: {error}")
            return
        timestamp = _seconds(message.stamp)
        candidate: TerminationCandidate | None = None
        with self._lock:
            if (
                self._last_state_sequence is not None
                and message.sequence <= self._last_state_sequence
            ):
                return
            self._last_state_sequence = message.sequence
            if state in {EpisodeState.PREPARING, EpisodeState.READY}:
                self._evaluation.prepare()
                self._candidate_submitted = False
            elif state is EpisodeState.RUNNING:
                self._evaluation.start(timestamp)
                candidate = self._apply_agent_terminal_locked()
            elif state in {EpisodeState.TERMINATING, EpisodeState.FINISHED}:
                self._evaluation.finish(reason, timestamp)
        self._submit_candidate(candidate)

    def _on_agent_task_state(self, message: AgentTaskState) -> None:
        if not self._matches(message.experiment_id, message.episode_id):
            return
        if message.state not in {
            AgentTaskState.IDLE,
            AgentTaskState.RUNNING,
            AgentTaskState.SUCCEEDED,
            AgentTaskState.FAILED,
        }:
            self._node.get_logger().warning("ignoring unknown Agent task state")
            return
        candidate: TerminationCandidate | None = None
        with self._lock:
            if (
                self._last_agent_state_sequence is not None
                and message.sequence <= self._last_agent_state_sequence
            ):
                return
            self._last_agent_state_sequence = message.sequence
            if message.state in {AgentTaskState.IDLE, AgentTaskState.RUNNING}:
                self._pending_agent_terminal = None
            else:
                self._pending_agent_terminal = (
                    message.state,
                    _seconds(message.stamp),
                )
                candidate = self._apply_agent_terminal_locked()
        self._submit_candidate(candidate)

    def _on_odometry(self, message: Odometry) -> None:
        candidate: TerminationCandidate | None = None
        try:
            point = self._map_position(message)
            with self._lock:
                if not self._task_verified:
                    return
                candidate = self._evaluation.observe_position(
                    _seconds(message.header.stamp),
                    point,
                )
        except (
            TypeError,
            ValueError,
            PointNavValidationError,
            TransformException,
        ) as error:
            self._node.get_logger().warning(f"ignoring invalid odometry: {error}")
            return
        self._submit_candidate(candidate)

    def _on_clock(self, message: Clock) -> None:
        candidate: TerminationCandidate | None = None
        try:
            with self._lock:
                if not self._task_verified:
                    return
                candidate = self._evaluation.advance_clock(_seconds(message.clock))
        except ValueError as error:
            self._node.get_logger().warning(f"ignoring invalid simulation clock: {error}")
            return
        self._submit_candidate(candidate)

    def _submit_candidate(self, candidate: TerminationCandidate | None) -> None:
        if candidate is None:
            return
        with self._lock:
            if self._candidate_submitted:
                return
            self._candidate_submitted = True
        decision = self._submit_termination(
            candidate.reason,
            detail=candidate.detail,
        )
        if not decision.accepted:
            self._node.get_logger().warning(
                f"termination candidate was not accepted: {decision.detail}"
            )

    def _matches(self, experiment_id: str, episode_id: str) -> bool:
        return self._expected.matches_episode(experiment_id, episode_id)

    def _apply_agent_terminal_locked(self) -> TerminationCandidate | None:
        if self._pending_agent_terminal is None or not self._evaluation.running:
            return None
        state, timestamp = self._pending_agent_terminal
        if state == AgentTaskState.SUCCEEDED:
            return self._evaluation.report_agent_succeeded(timestamp)
        return self._evaluation.report_agent_failed(timestamp)

    def _map_position(self, message: Odometry) -> Point3D:
        source_frame = message.header.frame_id
        if not source_frame.strip():
            raise ValueError("odometry frame must not be empty")
        position = message.pose.pose.position
        if source_frame == self._expected.goal.frame_id:
            return Point3D(
                frame_id=source_frame,
                x=position.x,
                y=position.y,
                z=position.z,
            )

        stamped = PointStamped()
        stamped.header = message.header
        stamped.point = position
        transform = self._tf_buffer.lookup_transform(
            self._expected.goal.frame_id,
            source_frame,
            RclpyTime.from_msg(message.header.stamp),
            timeout=Duration(seconds=0.0),
        )
        transformed = do_transform_point(stamped, transform)
        return Point3D(
            frame_id=self._expected.goal.frame_id,
            x=transformed.point.x,
            y=transformed.point.y,
            z=transformed.point.z,
        )
