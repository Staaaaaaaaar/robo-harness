from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.client import Client
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.time import Time
from rh_interfaces.msg import ComponentStatus, EpisodeState
from rh_interfaces.srv import ResetEnv
from rosgraph_msgs.msg import Clock
from tf2_ros import Buffer, TransformListener

from rh_core import Pose3D
from rh_mock_env.node import RESET_ID_CONFLICT, MockEnvironmentNode
from rh_ros import (
    StatusMonitor,
    command_qos,
    latched_control_qos,
    pose_from_message,
    pose_to_message,
    sensor_qos,
)


@pytest.fixture
def ros_context() -> Iterator[None]:
    rclpy.init()
    try:
        yield
    finally:
        rclpy.shutdown()


def _client_node(prefix: str) -> Node:
    return rclpy.create_node(f"{prefix}_{uuid4().hex}")


def _spin_for(executor: SingleThreadedExecutor, duration_s: float) -> None:
    deadline = time.monotonic() + duration_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        executor.spin_once(timeout_sec=min(0.02, remaining))


def _spin_until(
    executor: SingleThreadedExecutor,
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
    assert predicate()


def _reset_request(*, request_id: str = "reset-1", x: float = 1.0) -> ResetEnv.Request:
    request = ResetEnv.Request()
    request.request_id = request_id
    request.experiment_id = "experiment-1"
    request.episode_id = "episode-1"
    request.initial_pose = pose_to_message(
        Pose3D("map", x, 2.0, 0.4, 0.1, -0.2, 0.3)
    )
    request.seed = 42
    return request


def _call_reset(
    executor: SingleThreadedExecutor,
    client: Client,
    request: ResetEnv.Request,
) -> ResetEnv.Response:
    assert client.wait_for_service(timeout_sec=2.0)
    future = client.call_async(request)
    _spin_until(executor, future.done)
    result = future.result()
    assert result is not None
    return result


def _episode_state(state: int, sequence: int) -> EpisodeState:
    message = EpisodeState()
    message.experiment_id = "experiment-1"
    message.episode_id = "episode-1"
    message.sequence = sequence
    message.state = state
    message.termination_reason = EpisodeState.NONE
    return message


def test_readiness_clock_odom_and_tf_are_available_to_late_joiner(
    ros_context: None,
) -> None:
    env = MockEnvironmentNode(node_name="mock_env_readiness")
    client = _client_node("mock_env_observer")
    executor = SingleThreadedExecutor()
    clocks: list[Clock] = []
    odometry: list[Odometry] = []
    try:
        # Create all consumers after the Env has published its initial state.
        status = StatusMonitor(client, "/roboharness/env/status", stale_timeout_s=2.0)
        client.create_subscription(Clock, "/clock", clocks.append, 1)
        client.create_subscription(Odometry, "/robot/odom", odometry.append, sensor_qos())
        tf_buffer = Buffer()
        transform_listener = TransformListener(tf_buffer, client, spin_thread=False)
        executor.add_node(env)
        executor.add_node(client)

        _spin_until(
            executor,
            lambda: status.tracker.is_ready("mock_env") and clocks and odometry,
        )
        _spin_until(
            executor,
            lambda: tf_buffer.can_transform("map", "base_link", Time()),
        )

        assert clocks[-1].clock.sec >= 0
        assert odometry[-1].header.frame_id == "odom"
        assert odometry[-1].child_frame_id == "base_link"
        assert transform_listener is not None
    finally:
        executor.shutdown()
        env.destroy_node()
        client.destroy_node()


def test_never_ready_fault_remains_observable_as_starting(ros_context: None) -> None:
    env = MockEnvironmentNode(
        node_name="mock_env_never_ready",
        parameter_overrides=[Parameter("never_ready", value=True)],
    )
    client = _client_node("mock_env_startup_observer")
    executor = SingleThreadedExecutor()
    try:
        status = StatusMonitor(client, "/roboharness/env/status", stale_timeout_s=2.0)
        executor.add_node(env)
        executor.add_node(client)
        _spin_until(executor, lambda: status.tracker.latest("mock_env") is not None)

        assert status.tracker.latest("mock_env").state == ComponentStatus.STARTING
        assert not status.tracker.is_ready("mock_env")
    finally:
        executor.shutdown()
        env.destroy_node()
        client.destroy_node()


def test_reset_is_complete_idempotent_and_motion_is_episode_gated(
    ros_context: None,
) -> None:
    env = MockEnvironmentNode(
        node_name="mock_env_motion",
        parameter_overrides=[Parameter("command_timeout_s", value=0.3)],
    )
    client = _client_node("mock_env_driver")
    executor = SingleThreadedExecutor()
    odometry: list[Odometry] = []
    try:
        reset_client = client.create_client(ResetEnv, "/roboharness/env/reset_episode")
        state_publisher = client.create_publisher(
            EpisodeState,
            "/roboharness/episode/state",
            latched_control_qos(),
        )
        command_publisher = client.create_publisher(
            Twist, "/robot/cmd_vel", command_qos()
        )
        client.create_subscription(Odometry, "/robot/odom", odometry.append, sensor_qos())
        executor.add_node(env)
        executor.add_node(client)
        _spin_until(
            executor,
            lambda: state_publisher.get_subscription_count() > 0
            and command_publisher.get_subscription_count() > 0,
        )

        response = _call_reset(executor, reset_client, _reset_request())
        assert response.success
        _spin_until(executor, lambda: bool(odometry))
        reset_pose = pose_from_message(_odom_as_pose(odometry[-1]))
        assert reset_pose.x == pytest.approx(1.0)
        assert reset_pose.y == pytest.approx(2.0)
        assert reset_pose.z == pytest.approx(0.4)
        assert reset_pose.roll == pytest.approx(0.1)
        assert reset_pose.pitch == pytest.approx(-0.2)
        assert reset_pose.yaw == pytest.approx(0.3)

        command = Twist()
        command.linear.x = 1.0
        command_publisher.publish(command)
        _spin_for(executor, 0.15)
        assert odometry[-1].pose.pose.position.x == pytest.approx(1.0)

        state_publisher.publish(_episode_state(EpisodeState.RUNNING, 0))
        _spin_for(executor, 0.1)
        command_publisher.publish(command)
        _spin_for(executor, 0.15)
        moved_x = odometry[-1].pose.pose.position.x
        assert moved_x > 1.0

        duplicate = _call_reset(executor, reset_client, _reset_request())
        assert duplicate.success
        _spin_for(executor, 0.05)
        assert odometry[-1].pose.pose.position.x > 1.0

        conflict = _call_reset(
            executor,
            reset_client,
            _reset_request(request_id="reset-1", x=9.0),
        )
        assert not conflict.success
        assert conflict.error_code == RESET_ID_CONFLICT

        state_publisher.publish(_episode_state(EpisodeState.FINISHED, 1))
        _spin_for(executor, 0.1)
        stopped_x = odometry[-1].pose.pose.position.x
        command_publisher.publish(command)
        _spin_for(executor, 0.15)
        assert odometry[-1].pose.pose.position.x == pytest.approx(stopped_x)
        assert odometry[-1].twist.twist.linear.x == 0.0
    finally:
        executor.shutdown()
        env.destroy_node()
        client.destroy_node()


def _odom_as_pose(odometry: Odometry) -> PoseStamped:
    message = PoseStamped()
    message.header = odometry.header
    message.header.frame_id = "map"
    message.pose = odometry.pose.pose
    return message


def test_command_watchdog_uses_simulation_time(ros_context: None) -> None:
    env = MockEnvironmentNode(
        node_name="mock_env_watchdog",
        parameter_overrides=[Parameter("command_timeout_s", value=0.1)],
    )
    client = _client_node("mock_env_watchdog_driver")
    executor = SingleThreadedExecutor()
    odometry: list[Odometry] = []
    try:
        reset_client = client.create_client(ResetEnv, "/roboharness/env/reset_episode")
        state_publisher = client.create_publisher(
            EpisodeState, "/roboharness/episode/state", latched_control_qos()
        )
        command_publisher = client.create_publisher(Twist, "/robot/cmd_vel", command_qos())
        client.create_subscription(Odometry, "/robot/odom", odometry.append, sensor_qos())
        executor.add_node(env)
        executor.add_node(client)
        _spin_until(
            executor,
            lambda: command_publisher.get_subscription_count() > 0
            and state_publisher.get_subscription_count() > 0,
        )
        assert _call_reset(executor, reset_client, _reset_request()).success
        state_publisher.publish(_episode_state(EpisodeState.RUNNING, 0))
        _spin_for(executor, 0.1)
        command = Twist()
        command.linear.x = 1.0
        command_publisher.publish(command)

        _spin_for(executor, 0.35)

        assert odometry
        assert odometry[-1].pose.pose.position.x > 1.0
        assert odometry[-1].twist.twist.linear.x == 0.0
    finally:
        executor.shutdown()
        env.destroy_node()
        client.destroy_node()


def test_reset_failure_clock_freeze_and_stale_heartbeat_are_injectable(
    ros_context: None,
) -> None:
    env = MockEnvironmentNode(
        node_name="mock_env_faults",
        parameter_overrides=[
            Parameter("reset_failure", value=True),
            Parameter("suppress_status_heartbeat", value=True),
        ],
    )
    client = _client_node("mock_env_fault_observer")
    executor = SingleThreadedExecutor()
    clocks: list[Clock] = []
    try:
        status = StatusMonitor(client, "/roboharness/env/status", stale_timeout_s=0.2)
        client.create_subscription(Clock, "/clock", clocks.append, 1)
        reset_client = client.create_client(ResetEnv, "/roboharness/env/reset_episode")
        executor.add_node(env)
        executor.add_node(client)
        _spin_until(executor, lambda: status.tracker.latest("mock_env") is not None and clocks)

        response = _call_reset(executor, reset_client, _reset_request())
        assert not response.success
        _spin_until(
            executor,
            lambda: status.tracker.latest("mock_env") is not None
            and status.tracker.latest("mock_env").state == ComponentStatus.ERROR,
        )

        env.set_parameters([Parameter("freeze_clock", value=True)])
        immutable_result = env.set_parameters(
            [Parameter("command_timeout_s", value=10.0)]
        )
        assert not immutable_result[0].successful
        assert "startup-only" in immutable_result[0].reason
        _spin_for(executor, 0.1)
        frozen = (clocks[-1].clock.sec, clocks[-1].clock.nanosec)
        _spin_for(executor, 0.25)
        assert (clocks[-1].clock.sec, clocks[-1].clock.nanosec) == frozen
        assert status.tracker.is_stale("mock_env")
    finally:
        executor.shutdown()
        env.destroy_node()
        client.destroy_node()
