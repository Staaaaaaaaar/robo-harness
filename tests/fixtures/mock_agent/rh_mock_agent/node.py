"""ROS 2 Mock Agent implementing the RoboHarness Agent contract."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import SetParametersResult
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.parameter import Parameter
from rh_interfaces.msg import AgentTaskState, ComponentStatus, EpisodeState, PointNavTask
from rh_interfaces.srv import ResetAgent
from rosgraph_msgs.msg import Clock as ClockMessage

from rh_mock_agent.model import MockAgentModel, ScriptSegment, VelocityCommand
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
    point_from_message,
)

INVALID_RESET = 2001
INJECTED_RESET_FAILURE = 2002
RESET_ID_CONFLICT = 2003
INJECTED_RUNTIME_ERROR = 2004


@dataclass(frozen=True, slots=True)
class ResetOutcome:
    success: bool
    error_code: int = 0
    detail: str = ""


class MockAgentNode(Node):
    """Deterministic black-box fixture for consumers of the Agent ROS contract."""

    def __init__(
        self,
        *,
        node_name: str = "rh_mock_agent",
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
        self.declare_parameter("script_durations_s", [1.0, 0.5])
        self.declare_parameter("script_linear_x", [0.5, 0.0])
        self.declare_parameter("script_linear_y", [0.0, 0.0])
        self.declare_parameter("script_angular_z", [0.0, 1.0])
        self.declare_parameter("ready_delay_s", 0.0)
        self.declare_parameter("never_ready", False)
        self.declare_parameter("reset_failure", False)
        self.declare_parameter("suppress_status_heartbeat", False)
        self.declare_parameter("inject_error", False)
        self.declare_parameter("error_after_s", -1.0)
        self.declare_parameter("crash_after_s", -1.0)

        self._model = MockAgentModel(self._script_from_parameters())
        self._sequence_guard = EpisodeSequenceGuard()
        self._reset_guard: IdempotentResetGuard[tuple[str, str], ResetOutcome] = (
            IdempotentResetGuard()
        )
        self._status = StatusPublisher(
            self,
            "/roboharness/agent/status",
            "mock_agent",
        )
        self._command_publisher = self.create_publisher(
            Twist,
            "/robot/cmd_vel",
            command_qos(),
        )
        self._task_state_publisher = self.create_publisher(
            AgentTaskState,
            "/roboharness/agent/task_state",
            latched_control_qos(),
        )
        self._task_state = AgentTaskState()
        self._task_subscription = self.create_subscription(
            PointNavTask,
            "/roboharness/task/pointnav",
            self._on_task,
            latched_control_qos(),
        )
        self._state_subscription = self.create_subscription(
            EpisodeState,
            "/roboharness/episode/state",
            self._on_episode_state,
            latched_control_qos(),
        )
        self._clock_subscription = self.create_subscription(
            ClockMessage,
            "/clock",
            self._on_clock,
            1,
        )
        self._reset_service = self.create_service(
            ResetAgent,
            "/roboharness/agent/reset_episode",
            self._on_reset,
        )

        steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._ready_timer = None
        self._error_timer = None
        self._crash_timer = None
        self.add_on_set_parameters_callback(self._validate_parameters)
        self._configure_delayed_faults(steady_clock)
        self._fault_timer = self.create_timer(
            0.05,
            self._sync_dynamic_faults,
            clock=steady_clock,
        )

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

    def _script_from_parameters(self) -> tuple[ScriptSegment, ...]:
        durations = self._float_array("script_durations_s")
        linear_x = self._float_array("script_linear_x")
        linear_y = self._float_array("script_linear_y")
        angular_z = self._float_array("script_angular_z")
        lengths = {len(durations), len(linear_x), len(linear_y), len(angular_z)}
        if lengths != {len(durations)} or not durations:
            raise ValueError("script parameter arrays must be non-empty and equal length")
        segments = []
        for index, duration in enumerate(durations):
            if duration <= 0.0:
                raise ValueError("script durations must be positive")
            segments.append(
                ScriptSegment(
                    round(duration * 1_000_000_000),
                    VelocityCommand(linear_x[index], linear_y[index], angular_z[index]),
                )
            )
        return tuple(segments)

    def _float_array(self, name: str) -> tuple[float, ...]:
        value = self.get_parameter(name).value
        if not isinstance(value, list | tuple) or any(
            isinstance(item, bool)
            or not isinstance(item, int | float)
            or not math.isfinite(item)
            for item in value
        ):
            raise ValueError(f"{name} must contain only finite numbers")
        return tuple(float(item) for item in value)

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

    def _optional_delay_parameter(self, name: str) -> float:
        value = self.get_parameter(name).value
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value == 0.0
        ):
            raise ValueError(f"{name} must be negative (disabled) or positive")
        return float(value)

    def _configure_delayed_faults(self, steady_clock: Clock) -> None:
        error_after = self._optional_delay_parameter("error_after_s")
        crash_after = self._optional_delay_parameter("crash_after_s")
        if error_after > 0.0:
            self._error_timer = self.create_timer(
                error_after,
                self._enter_injected_error,
                clock=steady_clock,
            )
        if crash_after > 0.0:
            self._crash_timer = self.create_timer(
                crash_after,
                self._raise_injected_crash,
                clock=steady_clock,
            )

    def _validate_parameters(
        self, parameters: Sequence[Parameter]
    ) -> SetParametersResult:
        dynamic_booleans = {
            "inject_error",
            "reset_failure",
            "suppress_status_heartbeat",
        }
        startup_only = {
            "crash_after_s",
            "error_after_s",
            "never_ready",
            "ready_delay_s",
            "script_angular_z",
            "script_durations_s",
            "script_linear_x",
            "script_linear_y",
            "use_sim_time",
        }
        for parameter in parameters:
            if parameter.name in startup_only:
                return SetParametersResult(
                    successful=False,
                    reason=f"{parameter.name} is startup-only",
                )
            if parameter.name in dynamic_booleans and not isinstance(
                parameter.value, bool
            ):
                return SetParametersResult(
                    successful=False,
                    reason=f"{parameter.name} must be a bool",
                )
        return SetParametersResult(successful=True)

    def _become_ready(self) -> None:
        if self._ready_timer is not None:
            self._ready_timer.cancel()
        if self._status.message.state == ComponentStatus.ERROR:
            return
        self._status.transition(ComponentStatus.READY, detail="mock agent ready")
        self._sync_dynamic_faults()

    def _on_reset(
        self, request: ResetAgent.Request, response: ResetAgent.Response
    ) -> ResetAgent.Response:
        fingerprint = (request.experiment_id, request.episode_id)
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

    def _execute_reset(self, request: ResetAgent.Request) -> ResetOutcome:
        self._status.transition(ComponentStatus.RESETTING, detail="resetting episode")
        if not request.experiment_id.strip() or not request.episode_id.strip():
            self._status.transition(ComponentStatus.READY, detail="reset request rejected")
            return ResetOutcome(
                False,
                INVALID_RESET,
                "experiment_id and episode_id must not be empty",
            )
        if self.get_parameter("reset_failure").value:
            detail = "injected reset failure"
            self._status.transition(
                ComponentStatus.ERROR,
                error_code=INJECTED_RESET_FAILURE,
                detail=detail,
                restart_required=True,
            )
            self._publish_zero()
            return ResetOutcome(False, INJECTED_RESET_FAILURE, detail)

        self._model.reset(request.experiment_id, request.episode_id)
        self._sequence_guard.activate(request.experiment_id, request.episode_id)
        self._task_state.experiment_id = request.experiment_id
        self._task_state.episode_id = request.episode_id
        self._task_state.sequence = 0
        self._task_state.state = AgentTaskState.IDLE
        self._publish_task_state(AgentTaskState.IDLE, "episode reset complete")
        self._publish_zero()
        self._status.transition(ComponentStatus.READY, detail="episode reset complete")
        return ResetOutcome(True)

    def _on_task(self, message: PointNavTask) -> None:
        try:
            fingerprint = self._task_fingerprint(message)
        except ConversionError as error:
            self.get_logger().warning(f"ignoring invalid PointNav task: {error}")
            return
        if self._model.accept_task(
            message.experiment_id,
            message.episode_id,
            fingerprint,
        ):
            self._publish_command()
        else:
            self.get_logger().warning("ignoring mismatched or conflicting PointNav task")

    @staticmethod
    def _task_fingerprint(message: PointNavTask) -> tuple[object, ...]:
        if not message.experiment_id.strip() or not message.episode_id.strip():
            raise ConversionError("task identity must not be empty")
        point = point_from_message(message.goal)
        if point.frame_id != "map":
            raise ConversionError("PointNav goal frame must be map")
        if (
            not math.isfinite(message.success_radius_m)
            or message.success_radius_m <= 0.0
            or not math.isfinite(message.timeout_s)
            or message.timeout_s <= 0.0
        ):
            raise ConversionError("PointNav radius and timeout must be finite and positive")
        return (
            message.goal.header.frame_id,
            struct.pack("!d", point.x),
            struct.pack("!d", point.y),
            struct.pack("!d", point.z),
            struct.pack("!d", message.success_radius_m),
            struct.pack("!d", message.timeout_s),
            message.seed,
        )

    def _on_episode_state(self, message: EpisodeState) -> None:
        if not self._sequence_guard.accept(message):
            return
        try:
            state, _ = episode_state_values_from_message(message)
        except ConversionError:
            self._model.set_episode_running(False)
            self._publish_zero()
            return
        running = state.value == EpisodeState.RUNNING
        self._model.set_episode_running(running)
        if running and self._task_state.state != AgentTaskState.RUNNING:
            self._publish_task_state(AgentTaskState.RUNNING, "agent execution started")
        elif (
            state.value in {EpisodeState.TERMINATING, EpisodeState.FINISHED}
            and self._task_state.state == AgentTaskState.RUNNING
        ):
            self._publish_task_state(AgentTaskState.IDLE, "episode no longer running")
        self._publish_command()

    def _on_clock(self, message: ClockMessage) -> None:
        simulation_time_ns = (
            int(message.clock.sec) * 1_000_000_000 + int(message.clock.nanosec)
        )
        self._model.advance_clock(simulation_time_ns)
        self._sync_dynamic_faults()
        self._publish_command()

    def _sync_dynamic_faults(self) -> None:
        self._status.set_heartbeat_enabled(
            not self.get_parameter("suppress_status_heartbeat").value
        )
        if self.get_parameter("inject_error").value:
            self._enter_injected_error()

    def _enter_injected_error(self) -> None:
        if self._error_timer is not None:
            self._error_timer.cancel()
        if self._ready_timer is not None:
            self._ready_timer.cancel()
        self._model.set_episode_running(False)
        self._publish_zero()
        if (
            self._status.message.state == ComponentStatus.ERROR
            and self._status.message.error_code == INJECTED_RUNTIME_ERROR
        ):
            return
        self._status.transition(
            ComponentStatus.ERROR,
            error_code=INJECTED_RUNTIME_ERROR,
            detail="injected runtime error",
            restart_required=True,
        )

    def _raise_injected_crash(self) -> None:
        if self._crash_timer is not None:
            self._crash_timer.cancel()
        self._publish_zero()
        raise RuntimeError("injected mock agent crash")

    def _publish_zero(self) -> None:
        message = Twist()
        self._command_publisher.publish(message)

    def _publish_task_state(self, state: int, detail: str) -> None:
        if self._task_state.state != state and self._task_state.experiment_id:
            self._task_state.sequence += 1
        self._task_state.stamp = self.get_clock().now().to_msg()
        self._task_state.state = state
        self._task_state.detail = detail
        self._task_state_publisher.publish(self._task_state)

    def _publish_command(self) -> None:
        command = self._model.snapshot.command
        message = Twist()
        message.linear.x = command.linear_x
        message.linear.y = command.linear_y
        message.angular.z = command.angular_z
        self._command_publisher.publish(message)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MockAgentNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
