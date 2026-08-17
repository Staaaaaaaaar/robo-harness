"""ROS 2 Mock Environment implementing the RoboHarness Env contract."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import rclpy
from builtin_interfaces.msg import Time
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import SetParametersResult
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import ComponentStatus, EpisodeState
from rh_interfaces.srv import ResetEnv
from rosgraph_msgs.msg import Clock as ClockMessage
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster

from rh_mock_env.model import MockEnvironmentModel, VelocityCommand
from rh_ros import (
    ConversionError,
    EpisodeSequenceGuard,
    IdempotentResetGuard,
    InvalidProtocolValueError,
    ResetRequestConflictError,
    StatusPublisher,
    command_qos,
    episode_state_values_from_message,
    latched_control_qos,
    pose_from_message,
    rpy_to_quaternion,
    sensor_qos,
)

INVALID_RESET = 1001
INJECTED_RESET_FAILURE = 1002
RESET_ID_CONFLICT = 1003


@dataclass(frozen=True, slots=True)
class ResetOutcome:
    success: bool
    error_code: int = 0
    detail: str = ""


class MockEnvironmentNode(Node):
    """Deterministic black-box fixture for consumers of the Env ROS contract."""

    def __init__(
        self,
        *,
        node_name: str = "rh_mock_env",
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        overrides = list(parameter_overrides or [])
        if not any(parameter.name == "use_sim_time" for parameter in overrides):
            overrides.append(Parameter("use_sim_time", value=True))
        super().__init__(
            node_name,
            parameter_overrides=overrides,
            automatically_declare_parameters_from_overrides=False,
        )
        self.declare_parameter("update_rate_hz", 20.0)
        self.declare_parameter("command_timeout_s", 0.5)
        self.declare_parameter("ready_delay_s", 0.0)
        self.declare_parameter("never_ready", False)
        self.declare_parameter("reset_failure", False)
        self.declare_parameter("freeze_clock", False)
        self.declare_parameter("suppress_status_heartbeat", False)

        update_rate_hz = self._positive_parameter("update_rate_hz")
        self._step_ns = round(1_000_000_000 / update_rate_hz)
        self._model = MockEnvironmentModel(
            command_timeout_s=self._positive_parameter("command_timeout_s")
        )
        self._sequence_guard = EpisodeSequenceGuard()
        self._reset_guard: IdempotentResetGuard[tuple[object, ...], ResetOutcome] = (
            IdempotentResetGuard()
        )
        self._status = StatusPublisher(
            self,
            "/roboharness/env/status",
            "mock_env",
        )

        self._clock_publisher = self.create_publisher(ClockMessage, "/clock", 1)
        self._odom_publisher = self.create_publisher(
            Odometry, "/robot/odom", sensor_qos()
        )
        self._tf_broadcaster = TransformBroadcaster(self)
        self._static_tf_broadcaster = StaticTransformBroadcaster(self)
        self._cmd_subscription = self.create_subscription(
            Twist,
            "/robot/cmd_vel",
            self._on_command,
            command_qos(),
        )
        self._state_subscription = self.create_subscription(
            EpisodeState,
            "/roboharness/episode/state",
            self._on_episode_state,
            latched_control_qos(),
        )
        self._reset_service = self.create_service(
            ResetEnv,
            "/roboharness/env/reset_episode",
            self._on_reset,
        )
        steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._update_timer = self.create_timer(
            1.0 / update_rate_hz,
            self._on_update,
            clock=steady_clock,
        )
        self._ready_timer = None
        self.add_on_set_parameters_callback(self._validate_fault_parameters)
        self._publish_static_tf()
        self._publish_runtime_state()

        ready_delay = self._non_negative_parameter("ready_delay_s")
        if not self.get_parameter("never_ready").value:
            if ready_delay == 0.0:
                self._become_ready()
            else:
                self._ready_timer = self.create_timer(
                    ready_delay,
                    self._become_ready,
                    clock=steady_clock,
                )

    def _positive_parameter(self, name: str) -> float:
        value = self.get_parameter(name).value
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0.0
        ):
            raise ValueError(f"{name} must be positive")
        return float(value)

    def _non_negative_parameter(self, name: str) -> float:
        value = self.get_parameter(name).value
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value < 0.0
        ):
            raise ValueError(f"{name} must be non-negative")
        return float(value)

    def _validate_fault_parameters(
        self, parameters: Sequence[Parameter]
    ) -> SetParametersResult:
        boolean_parameters = {
            "freeze_clock",
            "reset_failure",
            "suppress_status_heartbeat",
        }
        startup_only_parameters = {
            "command_timeout_s",
            "never_ready",
            "ready_delay_s",
            "update_rate_hz",
            "use_sim_time",
        }
        for parameter in parameters:
            if parameter.name in startup_only_parameters:
                return SetParametersResult(
                    successful=False,
                    reason=f"{parameter.name} is startup-only",
                )
            if parameter.name in boolean_parameters and not isinstance(parameter.value, bool):
                return SetParametersResult(
                    successful=False,
                    reason=f"{parameter.name} must be a bool",
                )
        return SetParametersResult(successful=True)

    def _become_ready(self) -> None:
        if self._ready_timer is not None:
            self._ready_timer.cancel()
        self._status.transition(ComponentStatus.READY, detail="mock environment ready")
        if self.get_parameter("suppress_status_heartbeat").value:
            self._status.set_heartbeat_enabled(False)

    def _on_reset(
        self, request: ResetEnv.Request, response: ResetEnv.Response
    ) -> ResetEnv.Response:
        fingerprint = self._reset_fingerprint(request)
        try:
            outcome = self._reset_guard.execute(
                request.request_id,
                fingerprint,
                lambda: self._execute_reset(request),
            )
        except ResetRequestConflictError as error:
            outcome = ResetOutcome(False, RESET_ID_CONFLICT, str(error))
        except InvalidProtocolValueError as error:
            outcome = ResetOutcome(False, INVALID_RESET, str(error))
        response.success = outcome.success
        response.error_code = outcome.error_code
        response.detail = outcome.detail
        return response

    def _execute_reset(self, request: ResetEnv.Request) -> ResetOutcome:
        self._status.transition(ComponentStatus.RESETTING, detail="resetting episode")
        try:
            pose = pose_from_message(request.initial_pose)
            if pose.frame_id != "map":
                raise ConversionError("initial pose frame must be map")
            if not request.experiment_id.strip() or not request.episode_id.strip():
                raise ConversionError("experiment_id and episode_id must not be empty")
        except ConversionError as error:
            self._status.transition(ComponentStatus.READY, detail="reset request rejected")
            return ResetOutcome(False, INVALID_RESET, str(error))

        if self.get_parameter("reset_failure").value:
            detail = "injected reset failure"
            self._status.transition(
                ComponentStatus.ERROR,
                error_code=INJECTED_RESET_FAILURE,
                detail=detail,
                restart_required=True,
            )
            return ResetOutcome(False, INJECTED_RESET_FAILURE, detail)

        self._model.reset(pose)
        self._sequence_guard.activate(request.experiment_id, request.episode_id)
        self._publish_runtime_state()
        self._status.transition(ComponentStatus.READY, detail="episode reset complete")
        return ResetOutcome(True)

    @staticmethod
    def _reset_fingerprint(request: ResetEnv.Request) -> tuple[object, ...]:
        pose = request.initial_pose.pose
        return (
            request.experiment_id,
            request.episode_id,
            request.initial_pose.header.frame_id,
            struct.pack("!d", pose.position.x),
            struct.pack("!d", pose.position.y),
            struct.pack("!d", pose.position.z),
            struct.pack("!d", pose.orientation.x),
            struct.pack("!d", pose.orientation.y),
            struct.pack("!d", pose.orientation.z),
            struct.pack("!d", pose.orientation.w),
            request.seed,
        )

    def _on_episode_state(self, message: EpisodeState) -> None:
        if not self._sequence_guard.accept(message):
            return
        try:
            state, _ = episode_state_values_from_message(message)
        except ConversionError:
            self._model.set_episode_running(False)
            return
        self._model.set_episode_running(state.value == EpisodeState.RUNNING)

    def _on_command(self, message: Twist) -> None:
        self._model.receive_command(
            VelocityCommand(
                linear_x=message.linear.x,
                linear_y=message.linear.y,
                angular_z=message.angular.z,
            )
        )

    def _on_update(self) -> None:
        if self.get_parameter("suppress_status_heartbeat").value:
            self._status.set_heartbeat_enabled(False)
        else:
            self._status.set_heartbeat_enabled(True)
        if not self.get_parameter("freeze_clock").value:
            self._model.step(self._step_ns)
        self._publish_runtime_state()

    def _publish_runtime_state(self) -> None:
        stamp = self._time_message(self._model.snapshot.simulation_time_ns)
        clock = ClockMessage()
        clock.clock = stamp
        self._clock_publisher.publish(clock)

        snapshot = self._model.snapshot
        quaternion = rpy_to_quaternion(
            snapshot.pose.roll,
            snapshot.pose.pitch,
            snapshot.pose.yaw,
        )
        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = snapshot.pose.x
        odom.pose.pose.position.y = snapshot.pose.y
        odom.pose.pose.position.z = snapshot.pose.z
        odom.pose.pose.orientation = quaternion
        odom.twist.twist.linear.x = snapshot.command.linear_x
        odom.twist.twist.linear.y = snapshot.command.linear_y
        odom.twist.twist.angular.z = snapshot.command.angular_z
        self._odom_publisher.publish(odom)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_link"
        transform.transform.translation.x = snapshot.pose.x
        transform.transform.translation.y = snapshot.pose.y
        transform.transform.translation.z = snapshot.pose.z
        transform.transform.rotation = quaternion
        self._tf_broadcaster.sendTransform(transform)

    def _publish_static_tf(self) -> None:
        transform = TransformStamped()
        transform.header.frame_id = "map"
        transform.child_frame_id = "odom"
        transform.transform.rotation.w = 1.0
        self._static_tf_broadcaster.sendTransform(transform)

    @staticmethod
    def _time_message(nanoseconds: int) -> Time:
        message = Time()
        message.sec, message.nanosec = divmod(nanoseconds, 1_000_000_000)
        return message


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MockEnvironmentNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
